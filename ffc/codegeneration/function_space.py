# -*- coding: utf-8 -*-
# Copyright (C) 2011-2018 Marie E. Rognes and Garth N. Wells
#
# This file is part of FFC (https://www.fenicsproject.org)
#
# SPDX-License-Identifier:    LGPL-3.0-or-later
#
# Based on original implementation by Martin Alnes and Anders Logg

# NB: generate_dolfin_namespace(...) assumes that if a coefficient has
# the same name in multiple forms, it is indeed the same coefficient:


def ufc_function_space_generator(form):
# def ufc_function_space_generator(form, prefix, classname):
    """Generate UFC code for a function space"""
    # print("*** function  space")

    blocks_h = []
    blocks_c = []

    # prefix = "foo"
    # classname = "bar"

    # print(form.keys())
    # print("^^^^^^^^^^^^^^^^^^^")
    # print("classname:", form["classname"])
    # print("prefix:", form["prefix"])
    # print("rank:", form["rank"])
    # print("create_finite_element:", form["create_finite_element"])
    # print("^^^^^^^^^^^^^^^^^^^")

    # Generate code for "Form_x_FunctionSpace_y" factories
    for i in range(form["rank"]):
        args = {
            "prefix": form["prefix"],
            "classname": "{}_functionspace_{}".format(form["classname"], i),
            "finite_element_classname": form["create_finite_element"][i],
            "dofmap_classname": form["create_dofmap"][i],
            "coordinate_map_classname": form["create_coordinate_mapping"][0]
        }
        blocks_h += [FUNCTION_SPACE_TEMPLATE_DECL.format_map(args)]
        blocks_c += [FUNCTION_SPACE_TEMPLATE_IMPL.format_map(args)]

    # print(blocks_h)
    # print(blocks_c[1])
    return "test"
    # return "\n".join(blocks_h) + code_h + "\n /* End coefficient typedefs */\n", "\n".join(blocks_c)


FUNCTION_SPACE_TEMPLATE_DECL = """\
ufc_function_space* {prefix}_{classname}_create(void);
"""

FUNCTION_SPACE_TEMPLATE_IMPL = """\
ufc_function_space* {prefix}_{classname}_create(void)
{{
  ufc_function_space* space = (ufc_function_space*) malloc(sizeof(*space));
  space->element = create_{finite_element_classname};
  space->dofmap = create_{dofmap_classname};
  space->coordinate_mapping = {coordinate_map_classname};
  return space;
}}
"""
