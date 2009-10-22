"QuadratureTransformer (optimised) for quadrature code generation to translate UFL expressions."

__author__ = "Kristian B. Oelgaard (k.b.oelgaard@tudelft.nl)"
__date__ = "2009-03-18 -- 2009-10-19"
__copyright__ = "Copyright (C) 2009 Kristian B. Oelgaard"
__license__  = "GNU GPL version 3 or any later version"

# Python modules.
from numpy import shape

# UFL common.
from ufl.common import product

# UFL Classes.
from ufl.classes import FixedIndex
from ufl.classes import IntValue
from ufl.classes import FloatValue
from ufl.classes import Function

# UFL Algorithms.
from ufl.algorithms.printing import tree_format

# FFC common modules.
from ffc.common.log import info, debug, error

# FFC fem modules.
from ffc.fem.finiteelement import AFFINE, CONTRAVARIANT_PIOLA, COVARIANT_PIOLA

# Utility and optimisation functions for quadraturegenerator.
from quadraturetransformerbase import QuadratureTransformerBase
from quadraturegenerator_utils import generate_psi_name
from quadraturegenerator_utils import create_permutations

from symbolics import set_format
from symbolics import create_float
from symbolics import create_symbol
from symbolics import create_product
from symbolics import create_sum
from symbolics import create_fraction
from symbolics import BASIS, IP, GEO, CONST
from symbolics import optimise_code

class QuadratureTransformerOpt(QuadratureTransformerBase):
    "Transform UFL representation to quadrature code."

    def __init__(self, form_representation, domain_type, optimise_options, format):

        # Initialise base class.
        QuadratureTransformerBase.__init__(self, form_representation, domain_type, optimise_options, format)
        set_format(format)

    # -------------------------------------------------------------------------
    # Start handling UFL classes.
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # AlgebraOperators (algebra.py).
    # -------------------------------------------------------------------------
    def sum(self, o, *operands):
        #print("Visiting Sum: " + o.__repr__() + "\noperands: " + "\n".join(map(str, operands)))

        code = {}
        # Loop operands that has to be summend.
        for op in operands:
            # If entries does already exist we can add the code, otherwise just
            # dump them in the element tensor.
            for key, val in op.items():
                if key in code:
                    code[key].append(val)
                else:
                    code[key] = [val]

        # Add sums and group if necessary.
        for key, val in code.items():
            if len(val) > 1:
                code[key] = create_sum(val)
            elif val:
                code[key] = val[0]
            else:
                error("Where did the values go?")

        return code

    def product(self, o, *operands):
        #print("\n\nVisiting Product:\n" + str(tree_format(o)))

        permute = []
        not_permute = []

        # Sort operands in objects that needs permutation and objects that does not.
        for op in operands:
            if len(op) > 1 or (op and op.keys()[0] != ()):
                permute.append(op)
            elif op:
                not_permute.append(op[()])

        # Create permutations.
        # TODO: After all indices have been expanded I don't think that we'll
        # ever get more than a list of entries and values.
        permutations = create_permutations(permute)

        #print("\npermute: " + str(permute))
        #print("\nnot_permute: " + str(not_permute))
        #print("\npermutations: " + str(permutations))

        # Create code.
        code ={}
        if permutations:
            for key, val in permutations.items():
                # Sort key in order to create a unique key.
                l = list(key)
                l.sort()
                # TODO: I think this check can be removed for speed since we
                # just have a list of objects we should never get any conflicts here.
                if tuple(l) in code:
                    error("This key should not be in the code.")
                code[tuple(l)] = create_product(val + not_permute)
        else:
            return {():create_product(not_permute)}
        return code

    def division(self, o, *operands):
        #print("\n\nVisiting Division: " + o.__repr__() + "with operands: " + "\n".join(map(str,operands)))

        if len(operands) != 2:
            error("Expected exactly two operands (numerator and denominator): " + operands.__repr__())

        # Get the code from the operands.
        numerator_code, denominator_code = operands

        # TODO: Are these safety checks needed?
        if not () in denominator_code and len(denominator_code) != 1:
            error("Only support function type denominator: " + str(denominator_code))

        code = {}
        # Get denominator and create new values for the numerator.
        denominator = denominator_code[()]
        for key, val in numerator_code.items():
            code[key] = create_fraction(val, denominator)

        return code

    def power(self, o):
        #print("\n\nVisiting Power: " + o.__repr__())

        # Get base and exponent.
        base, expo = o.operands()

        # Visit base to get base code.
        base_code = self.visit(base)

        # TODO: Are these safety checks needed?
        if not () in base_code and len(base_code) != 1:
            error("Only support function type base: " + str(base_code))

        # Get the base code and create power.
        val = base_code[()]

        # Handle different exponents
        if isinstance(expo, IntValue):
            return {(): create_product([val]*expo.value())}
        elif isinstance(expo, FloatValue):
            exp = self.format["floating point"](expo.value())
            sym = create_symbol(self.format["std power"](str(val), exp), val.t)
            sym.base_expr = val
            sym.base_op = 1 # Add one operation for the pow() function.
            return {(): sym}
        elif isinstance(expo, Function):
            exp = self.visit(expo)
            sym = create_symbol(self.format["std power"](str(val), exp[()]), val.t)
            sym.base_expr = val
            sym.base_op = 1 # Add one operation for the pow() function.
            return {(): sym}
        else:
            error("power does not support this exponent: " + repr(expo))

    def abs(self, o, *operands):
        #print("\n\nVisiting Abs: " + o.__repr__() + "with operands: " + "\n".join(map(str,operands)))

        # TODO: Are these safety checks needed?
        if len(operands) != 1 and not () in operands[0] and len(operands[0]) != 1:
            error("Abs expects one operand of function type: " + str(operands))

        # Take absolute value of operand.
        val = operands[0][()]
        new_val = create_symbol(self.format["absolute value"](str(val)), val.t)
        new_val.base_expr = val
        new_val.base_op = 1 # Add one operation for taking the absolute value.
        return {():new_val}

    # -------------------------------------------------------------------------
    # FacetNormal (geometry.py).
    # -------------------------------------------------------------------------
    def facet_normal(self, o,  *operands):
        #print("Visiting FacetNormal:")

        # Get the component
        components = self.component()

        # Safety checks.
        if operands:
            error("Didn't expect any operands for FacetNormal: " + str(operands))
        if len(components) != 1:
            error("FacetNormal expects 1 component index: " + str(components))

        normal_component = self.format["normal component"](self.restriction, components[0])
        return {(): create_symbol(normal_component, GEO)}

    def create_basis_function(self, ufl_basis_function, derivatives, component, local_comp,
                  local_offset, ffc_element, transformation, multiindices):
        "Create code for basis functions, and update relevant tables of used basis."

        # Prefetch formats to speed up code generation.
        format_transform     = self.format["transform"]
        format_detJ          = self.format["determinant"]

        code = {}

        # Affince mapping
        if transformation == AFFINE:
            # Loop derivatives and get multi indices.
            for multi in multiindices:
                deriv = [multi.count(i) for i in range(self.geo_dim)]
                if not any(deriv):
                    deriv = []

                # Call function to create mapping and basis name.
                mapping, basis = self._create_mapping_basis(component, deriv, ufl_basis_function, ffc_element)

                # Add transformation if needed.
                if mapping in code:
                    code[mapping].append(self.__apply_transform(basis, derivatives, multi))
                else:
                    code[mapping] = [self.__apply_transform(basis, derivatives, multi)]

        # Handle non-affine mappings.
        else:
            # Loop derivatives and get multi indices.
            for multi in multiindices:
                deriv = [multi.count(i) for i in range(self.geo_dim)]
                if not any(deriv):
                    deriv = []
                for c in range(self.geo_dim):
                    # Call function to create mapping and basis name.
                    mapping, basis = self._create_mapping_basis(c + local_offset, deriv, ufl_basis_function, ffc_element)

                    # Multiply basis by appropriate transform.
                    if transformation == COVARIANT_PIOLA:
                        dxdX = create_symbol(format_transform("JINV", c, local_comp, self.restriction), GEO)
                        basis = create_product([dxdX, basis])
                    elif transformation == CONTRAVARIANT_PIOLA:
                        detJ = create_fraction(create_float(1), create_symbol(format_detJ(self.restriction), GEO))
                        dXdx = create_symbol(format_transform("J", c, local_comp, self.restriction), GEO)
                        basis = create_product([detJ, dXdx, basis])
                    else:
                        error("Transformation is not supported: " + str(transformation))

                    # Add transformation if needed.
                    if mapping in code:
                        code[mapping].append(self.__apply_transform(basis, derivatives, multi))
                    else:
                        code[mapping] = [self.__apply_transform(basis, derivatives, multi)]

        # Add sums and group if necessary.
        for key, val in code.items():
            if len(val) > 1:
                code[key] = create_sum(val)
            else:
                code[key] = val[0]

        return code

    def create_function(self, ufl_function, derivatives, component, local_comp,
                  local_offset, ffc_element, quad_element, transformation, multiindices):
        "Create code for basis functions, and update relevant tables of used basis."

        # Prefetch formats to speed up code generation.
        format_transform     = self.format["transform"]
        format_detJ          = self.format["determinant"]

        code = []

        # Handle affine mappings.
        if transformation == AFFINE:
            # Loop derivatives and get multi indices.
            for multi in multiindices:
                deriv = [multi.count(i) for i in range(self.geo_dim)]
                if not any(deriv):
                    deriv = []
                # Call other function to create function name.
                function_name = self._create_function_name(component, deriv, quad_element, ufl_function, ffc_element)
                if not function_name:
                    continue

                # Add transformation if needed.
                code.append(self.__apply_transform(function_name, derivatives, multi))

        # Handle non-affine mappings.
        else:
            # Loop derivatives and get multi indices.
            for multi in multiindices:
                deriv = [multi.count(i) for i in range(self.geo_dim)]
                if not any(deriv):
                    deriv = []
                for c in range(self.geo_dim):
                    function_name = self._create_function_name(c + local_offset, deriv, quad_element, ufl_function, ffc_element)

                    # Multiply basis by appropriate transform.
                    if transformation == COVARIANT_PIOLA:
                        dxdX = create_symbol(format_transform("JINV", c, local_comp, self.restriction), GEO)
                        function_name = create_product([dxdX, function_name])
                    elif transformation == CONTRAVARIANT_PIOLA:
                        detJ = create_fraction(create_float(1), create_symbol(format_detJ(self.restriction), GEO))
                        dXdx = create_symbol(format_transform("J", c, local_comp, self.restriction), GEO)
                        function_name = create_product([detJ, dXdx, function_name])
                    else:
                        error("Transformation is not supported: ", str(transformation))

                    # Add transformation if needed.
                    code.append(self.__apply_transform(function_name, derivatives, multi))
        if not code:
            return create_float(0.0)
        elif len(code) > 1:
            code = create_sum(code)
        else:
            code = code[0]

        return code

    # -------------------------------------------------------------------------
    # Helper functions for BasisFunction and Function).
    # -------------------------------------------------------------------------
    def __apply_transform(self, function, derivatives, multi):
        "Apply transformation (from derivatives) to basis or function."
        format_transform     = self.format["transform"]

        # Add transformation if needed.
        transforms = []
        for i, direction in enumerate(derivatives):
            ref = multi[i]
            t = format_transform("JINV", ref, direction, self.restriction)
            transforms.append(create_symbol(t, GEO))
        transforms.append(function)
        return create_product(transforms)

    # -------------------------------------------------------------------------
    # Helper functions for transformation of UFL objects in base class
    # -------------------------------------------------------------------------
    def _create_symbol(self, symbol, domain):
        return {():create_symbol(symbol, domain)}

    def _create_product(self, symbols):
        return create_product(symbols)

    def _format_scalar_value(self, value):
        #print("format_scalar_value: %d" % value)
        if value is None:
            return {():create_float(0.0)}
        return {():create_float(value)}

    def _math_function(self, operands, format_function):
        #print("Calling _math_function() of optimisedquadraturetransformer.")
        # TODO: Are these safety checks needed?
        if len(operands) != 1 and not () in operands[0] and len(operands[0]) != 1:
            error("MathFunctions expect one operand of function type: " + str(operands))
        # Use format function on value of operand.
        operand = operands[0]
        for key, val in operand.items():
            new_val = create_symbol(format_function(str(val)), val.t)
            new_val.base_expr = val
            new_val.base_op = 1 # Add one operation for the math function.
            operand[key] = new_val
        return operand

    # -------------------------------------------------------------------------
    # Helper functions for code_generation()
    # -------------------------------------------------------------------------
    def _count_operations(self, expression):
        return expression.ops()

    def _create_entry_value(self, val, weight, scale_factor):
        zero = False
        # Multiply value by weight and determinant

        # Multiply value by weight and determinant
        value = create_product([val, weight, create_symbol(scale_factor, GEO)])
        value = optimise_code(value, self.ip_consts, self.geo_consts, self.trans_set)

        # Check if value is zero
        if not value.val:
            zero = True
        # Update the set of used psi tables through the name map if the value is not zero.
        else:
            self.used_psi_tables.update([self.psi_tables_map[b] for b in value.get_unique_vars(BASIS)])

        return value, zero

    def _update_used_psi_tables(self):
        # Nothing to be done for optimised transformer (handled in _create_entry_value)
        pass
