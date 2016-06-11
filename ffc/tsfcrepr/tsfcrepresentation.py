# Copyright (C) 2016 Miklos Homolya, Lawrence Mitchell, Jan Blechta
#
# This file is part of FFC and contains snippets originally from tsfc.
#
# FFC is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# FFC is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with FFC. If not, see <http://www.gnu.org/licenses/>.

import collections

import gem
import gem.optimise as opt
import gem.impero_utils as impero_utils

from tsfc import fem, ufl_utils
from tsfc.coffee import generate as generate_coffee
from tsfc.kernel_interface import KernelBuilder, needs_cell_orientations
from tsfc.quadrature import create_quadrature, QuadratureRule

from ffc.log import info, error, begin, end, debug_ir, ffc_assert, warning
from ffc.representationutils import initialize_integral_ir


def compute_integral_ir(integral_data,
                        form_data,
                        form_id,
                        element_numbers,
                        parameters):
    "Compute intermediate represention of integral."

    info("Computing tsfc representation")

    # Initialise representation
    IR = initialize_integral_ir("tsfc", integral_data, form_data, form_id)

    # Remove these here, they're handled below.
    parameters = parameters.copy()
    if parameters.get("quadrature_degree") in ["auto", -1, "-1"]:
        del parameters["quadrature_degree"]
    if parameters.get("quadrature_rule") == "auto":
        del parameters["quadrature_rule"]

    integral_type = integral_data.integral_type
    mesh = integral_data.domain
    cell = integral_data.domain.ufl_cell()
    arguments = form_data.preprocessed_form.arguments()

    argument_indices = tuple(gem.Index(name=name) for arg, name in zip(arguments, ['j', 'k']))
    quadrature_indices = []

    builder = KernelBuilder(integral_type, integral_data.subdomain_id)
    return_variables = builder.set_arguments(arguments, argument_indices)

    coordinates = ufl_utils.coordinate_coefficient(mesh)
    if ufl_utils.is_element_affine(mesh.ufl_coordinate_element()):
        # For affine mesh geometries we prefer code generation that
        # composes well with optimisations.
        builder.set_coordinates(coordinates, "coords", mode='list_tensor')
    else:
        # Otherwise we use the approach that might be faster (?)
        builder.set_coordinates(coordinates, "coords")

    builder.set_coefficients(integral_data, form_data)

    # Map from UFL FiniteElement objects to Index instances.  This is
    # so we reuse Index instances when evaluating the same coefficient
    # multiple times with the same table.  Occurs, for example, if we
    # have multiple integrals here (and the affine coordinate
    # evaluation can be hoisted).
    index_cache = collections.defaultdict(gem.Index)

    irs = []
    for integral in integral_data.integrals:
        params = {}
        # Record per-integral parameters
        params.update(integral.metadata())
        # parameters override per-integral metadata
        params.update(parameters)

        # Check if the integral has a quad degree attached, otherwise use
        # the estimated polynomial degree attached by compute_form_data
        quadrature_degree = params.get("quadrature_degree",
                                       params["estimated_polynomial_degree"])
        #quad_rule = params.get("quadrature_rule",
        #                       create_quadrature(cell, integral_type,
        #                                         quadrature_degree))
        quad_rule = create_quadrature(cell, integral_type, quadrature_degree)

        if not isinstance(quad_rule, QuadratureRule):
            raise ValueError("Expected to find a QuadratureRule object, not a %s" %
                             type(quad_rule))

        integrand = ufl_utils.replace_coordinates(integral.integrand(), coordinates)
        integrand = ufl_utils.split_coefficients(integrand, builder.coefficient_split)
        quadrature_index = gem.Index(name='ip')
        quadrature_indices.append(quadrature_index)
        ir = fem.process(integral_type, cell, quad_rule.points,
                         quad_rule.weights, quadrature_index,
                         argument_indices, integrand,
                         builder.coefficient_mapper, index_cache)
        if parameters.get("unroll_indexsum"):
            ir = opt.unroll_indexsum(ir, max_extent=parameters["unroll_indexsum"])
        irs.append([(gem.IndexSum(expr, quadrature_index)
                     if quadrature_index in expr.free_indices
                     else expr)
                    for expr in ir])

    # Sum the expressions that are part of the same restriction
    ir = list(reduce(gem.Sum, e, gem.Zero()) for e in zip(*irs))

    # Need optimised roots for COFFEE
    ir = opt.remove_componenttensors(ir)

    # Look for cell orientations in the IR
    if needs_cell_orientations(ir):
        builder.require_cell_orientations()

    impero_c = impero_utils.compile_gem(return_variables, ir,
                                        tuple(quadrature_indices) + argument_indices,
                                        remove_zeros=True)

    # Generate COFFEE
    index_names = [(index, index.name) for index in argument_indices]
    if len(quadrature_indices) == 1:
        index_names.append((quadrature_indices[0], 'ip'))
    else:
        for i, quadrature_index in enumerate(quadrature_indices):
            index_names.append((quadrature_index, 'ip_%d' % i))

    body = generate_coffee(impero_c, index_names, ir, argument_indices)

    kernel_name = "%s_%s_integral_%s" % ("Form", integral_type, integral_data.subdomain_id)
    kernel = builder.construct_kernel(kernel_name, body)

    # Store tsfc generated part separately
    IR["tsfc"] = kernel

    return IR