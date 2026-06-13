#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Compare two groom Alembic files and report differences.

Usage:
    mayapy compare_groom_abc.py
    python compare_groom_abc.py
"""

import sys
import pathlib
_cask_path = pathlib.Path(__file__).parent.parent / "lib"
if _cask_path.exists():
    sys.path.insert(0, str(_cask_path))

import cask
from collections import OrderedDict


def get_all_properties_info(prop_obj, indent=0):
    """
    Recursively get all property information from a property object.

    :param prop_obj: cask.Property object
    :param indent: indentation level
    :return: dict with property information
    """
    info = {}

    if not hasattr(prop_obj, 'properties'):
        return info

    for name, prop in prop_obj.properties.items():
        prop_info = {
            'name': name,
            'metadata': dict(prop.metadata) if hasattr(prop, 'metadata') else {},
        }

        # Try to get values
        try:
            values = prop.values
            if values:
                # Show first few values, truncated
                sample_values = []
                for i, v in enumerate(values[:5]):
                    if hasattr(v, '__iter__') and not isinstance(v, str):
                        # It's an array-like object (imath types)
                        sample_values.append(f"[{len(v)} items]")
                    else:
                        sample_str = str(v)
                        sample_values.append(sample_str[:50] if len(sample_str) > 50 else sample_str)
                prop_info['value_count'] = len(values)
                prop_info['sample_values'] = sample_values
        except Exception as e:
            prop_info['value_error'] = str(e)

        # Recursively get child properties if this is a compound property
        if hasattr(prop, 'properties') and prop.properties:
            prop_info['children'] = get_all_properties_info(prop, indent + 1)

        info[name] = prop_info

    return info


def compare_properties_info(info1, info2, path=""):
    """
    Compare two property info dicts and return differences.

    :param info1: first property info dict
    :param info2: second property info dict
    :param path: current property path for reporting
    :return: list of difference descriptions
    """
    differences = []

    keys1 = set(info1.keys())
    keys2 = set(info2.keys())

    # Missing in file2
    for key in keys1 - keys2:
        differences.append(f"  {path}/{key}: Missing in file2")

    # Extra in file2
    for key in keys2 - keys1:
        differences.append(f"  {path}/{key}: Extra in file2")

    # Compare common keys
    for key in keys1 & keys2:
        p1 = info1[key]
        p2 = info2[key]
        current_path = f"{path}/{key}"

        # Compare metadata
        meta1 = p1.get('metadata', {})
        meta2 = p2.get('metadata', {})
        if meta1 != meta2:
            meta_diff = []
            for mk in set(meta1.keys()) | set(meta2.keys()):
                if meta1.get(mk) != meta2.get(mk):
                    meta_diff.append(f"{mk}: '{meta1.get(mk)}' vs '{meta2.get(mk)}'")
            if meta_diff:
                differences.append(f"  {current_path}: Metadata differs - {', '.join(meta_diff)}")

        # Compare value counts
        vc1 = p1.get('value_count')
        vc2 = p2.get('value_count')
        if vc1 is not None and vc2 is not None and vc1 != vc2:
            differences.append(f"  {current_path}: Value count differs - {vc1} vs {vc2}")

        # Compare sample values (for small arrays)
        sv1 = p1.get('sample_values', [])
        sv2 = p2.get('sample_values', [])
        if sv1 and sv2 and sv1 != sv2:
            # Only report if both have actual values (not just "[N items]")
            if not all(v.startswith('[') for v in sv1 + sv2):
                differences.append(f"  {current_path}: Values differ - {sv1[:3]} vs {sv2[:3]}")

        # Compare children recursively
        children1 = p1.get('children', {})
        children2 = p2.get('children', {})
        if children1 or children2:
            differences.extend(compare_properties_info(children1, children2, current_path))

    return differences


def collect_objects(obj, objects_dict, obj_type=None):
    """
    Recursively collect all objects from the archive by type.

    :param obj: cask object (Top, Xform, Curve, etc.)
    :param objects_dict: dict to store objects by path
    :param obj_type: optional filter by type
    """
    current_type = obj.type()

    # Store this object
    if obj_type is None or current_type == obj_type:
        objects_dict[obj.path()] = obj

    # Recurse into children
    for child in obj.children.values():
        collect_objects(child, objects_dict, obj_type)


def compare_curve_geometry(curve1, curve2):
    """
    Compare geometry data between two Curve objects.

    :param curve1: first cask.Curve
    :param curve2: second cask.Curve
    :return: list of differences
    """
    differences = []

    geom1 = curve1.properties.get('.geom')
    geom2 = curve2.properties.get('.geom')

    if geom1 is None and geom2 is None:
        return differences
    if geom1 is None:
        return ["  .geom: Missing in file1"]
    if geom2 is None:
        return ["  .geom: Missing in file2"]

    # Compare key geometry properties
    geom_props = ['P', '.P', 'nVertices', '.nVertices', 'width', '.width']

    for prop_name in geom_props:
        p1 = geom1.properties.get(prop_name)
        p2 = geom2.properties.get(prop_name)

        if p1 is None and p2 is None:
            continue
        if p1 is None:
            differences.append(f"  .geom/{prop_name}: Missing in file1")
            continue
        if p2 is None:
            differences.append(f"  .geom/{prop_name}: Extra in file1 (missing in file2)")
            continue

        try:
            v1 = p1.values
            v2 = p2.values
            if v1 and v2:
                if len(v1) != len(v2):
                    differences.append(f"  .geom/{prop_name}: Time sample count differs - {len(v1)} vs {len(v2)}")
                elif len(v1) > 0:
                    # Compare first sample
                    s1 = v1[0]
                    s2 = v2[0]
                    if len(s1) != len(s2):
                        differences.append(f"  .geom/{prop_name}: Element count differs - {len(s1)} vs {len(s2)}")
        except Exception as e:
            differences.append(f"  .geom/{prop_name}: Error comparing values - {e}")

    return differences


def compare_arb_geom_params(curve1, curve2):
    """
    Compare .arbGeomParams between two Curve objects.

    :param curve1: first cask.Curve
    :param curve2: second cask.Curve
    :return: list of differences
    """
    differences = []

    geom1 = curve1.properties.get('.geom')
    geom2 = curve2.properties.get('.geom')

    arb1 = geom1.properties.get('.arbGeomParams') if geom1 else None
    arb2 = geom2.properties.get('.arbGeomParams') if geom2 else None

    if arb1 is None and arb2 is None:
        return differences
    if arb1 is None:
        return ["  .arbGeomParams: Missing in file1"]
    if arb2 is None:
        return ["  .arbGeomParams: Missing in file2"]

    props1 = set(arb1.properties.keys())
    props2 = set(arb2.properties.keys())

    # Missing in file2
    for p in props1 - props2:
        differences.append(f"  .arbGeomParams/{p}: Missing in file2")

    # Extra in file2
    for p in props2 - props1:
        differences.append(f"  .arbGeomParams/{p}: Extra in file2")

    # Compare common properties
    for p in props1 & props2:
        prop1 = arb1.properties[p]
        prop2 = arb2.properties[p]

        # Compare metadata
        meta1 = dict(prop1.metadata) if hasattr(prop1, 'metadata') else {}
        meta2 = dict(prop2.metadata) if hasattr(prop2, 'metadata') else {}

        meta_diff = []
        for mk in set(meta1.keys()) | set(meta2.keys()):
            if meta1.get(mk) != meta2.get(mk):
                meta_diff.append(f"{mk}: '{meta1.get(mk)}' vs '{meta2.get(mk)}'")

        if meta_diff:
            differences.append(f"  .arbGeomParams/{p}: Metadata differs - {', '.join(meta_diff)}")

        # Compare values
        try:
            v1 = prop1.values
            v2 = prop2.values
            if v1 and v2 and len(v1) > 0 and len(v2) > 0:
                s1 = v1[0]
                s2 = v2[0]
                # For simple values, compare directly
                if isinstance(s1, (int, float, str)) and isinstance(s2, (int, float, str)):
                    if s1 != s2:
                        differences.append(f"  .arbGeomParams/{p}: Value differs - '{s1}' vs '{s2}'")
                elif hasattr(s1, '__len__') and hasattr(s2, '__len__'):
                    if len(s1) != len(s2):
                        differences.append(f"  .arbGeomParams/{p}: Array length differs - {len(s1)} vs {len(s2)}")
        except Exception as e:
            differences.append(f"  .arbGeomParams/{p}: Error comparing - {e}")

    return differences


def compare_user_properties(curve1, curve2):
    """
    Compare .userProperties between two Curve objects.

    :param curve1: first cask.Curve
    :param curve2: second cask.Curve
    :return: list of differences
    """
    differences = []

    geom1 = curve1.properties.get('.geom')
    geom2 = curve2.properties.get('.geom')

    up1 = geom1.properties.get('.userProperties') if geom1 else None
    up2 = geom2.properties.get('.userProperties') if geom2 else None

    if up1 is None and up2 is None:
        return differences
    if up1 is None:
        return ["  .userProperties: Missing in file1"]
    if up2 is None:
        return ["  .userProperties: Missing in file2"]

    props1 = set(up1.properties.keys()) if hasattr(up1, 'properties') else set()
    props2 = set(up2.properties.keys()) if hasattr(up2, 'properties') else set()

    if props1 != props2:
        differences.append(f"  .userProperties: Properties differ - {sorted(props1)} vs {sorted(props2)}")

    return differences


def compare_archives(file1_path, file2_path, fps=24):
    """
    Compare two Alembic archives in detail.

    :param file1_path: path to first .abc file (reference)
    :param file2_path: path to second .abc file (to compare)
    :param fps: frames per second
    """
    print("=" * 70)
    print("GROOM ABC COMPARISON REPORT")
    print("=" * 70)
    print(f"\nFile 1 (reference): {file1_path}")
    print(f"File 2 (compare):   {file2_path}")
    print()

    # Load archives
    try:
        archive1 = cask.Archive(file1_path, fps=fps)
        print(f"Loaded File 1: {archive1}")
        print(f"  Frame range: {archive1.start_frame()} - {archive1.end_frame()}, FPS: {archive1.fps}")
    except Exception as e:
        print(f"ERROR loading File 1: {e}")
        return

    try:
        archive2 = cask.Archive(file2_path, fps=fps)
        print(f"Loaded File 2: {archive2}")
        print(f"  Frame range: {archive2.start_frame()} - {archive2.end_frame()}, FPS: {archive2.fps}")
    except Exception as e:
        print(f"ERROR loading File 2: {e}")
        return

    all_differences = []

    # -------------------------------------------------------------------------
    # 1. Compare top-level children structure
    # -------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("1. HIERARCHY STRUCTURE COMPARISON")
    print("-" * 70)

    children1 = list(archive1.top.children.keys())
    children2 = list(archive2.top.children.keys())

    print(f"\nTop-level children count: {len(children1)} vs {len(children2)}")

    if children1 != children2:
        set1 = set(children1)
        set2 = set(children2)

        missing_in_2 = set1 - set2
        extra_in_2 = set2 - set1

        if missing_in_2:
            print(f"\n  Missing in File 2 ({len(missing_in_2)}):")
            for name in sorted(missing_in_2):
                print(f"    - {name}")
                all_differences.append(f"Hierarchy: '{name}' missing in File 2")

        if extra_in_2:
            print(f"\n  Extra in File 2 ({len(extra_in_2)}):")
            for name in sorted(extra_in_2):
                print(f"    + {name}")
                all_differences.append(f"Hierarchy: '{name}' extra in File 2")

        # Check order for common children
        common = set1 & set2
        order_diff = []
        for name in common:
            idx1 = children1.index(name)
            idx2 = children2.index(name)
            if idx1 != idx2:
                order_diff.append((name, idx1, idx2))

        if order_diff:
            print(f"\n  Order differences (name: pos_in_file1 vs pos_in_file2):")
            for name, i1, i2 in sorted(order_diff, key=lambda x: x[1])[:10]:
                print(f"    {name}: {i1} vs {i2}")
                all_differences.append(f"Order: '{name}' at position {i1} in File 1, {i2} in File 2")
    else:
        print("  Top-level children structure: IDENTICAL")

    # -------------------------------------------------------------------------
    # 2. Compare object types
    # -------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("2. OBJECT TYPE COMPARISON")
    print("-" * 70)

    type_diff = []
    for name in set(children1) & set(children2):
        obj1 = archive1.top.children[name]
        obj2 = archive2.top.children[name]
        type1 = obj1.type()
        type2 = obj2.type()

        if type1 != type2:
            type_diff.append((name, type1, type2))
            all_differences.append(f"Type: '{name}' is {type1} in File 1, {type2} in File 2")

    if type_diff:
        print(f"\n  Type differences:")
        for name, t1, t2 in type_diff:
            print(f"    {name}: {t1} vs {t2}")
    else:
        print("  All common children have matching types")

    # -------------------------------------------------------------------------
    # 3. Collect all curves for detailed comparison
    # -------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("3. CURVE DETAILED COMPARISON")
    print("-" * 70)

    curves1 = {}
    curves2 = {}

    collect_objects(archive1.top, curves1, "Curve")
    collect_objects(archive2.top, curves2, "Curve")

    print(f"\nTotal curves in File 1: {len(curves1)}")
    print(f"Total curves in File 2: {len(curves2)}")

    curve_paths1 = set(curves1.keys())
    curve_paths2 = set(curves2.keys())

    missing_curves = curve_paths1 - curve_paths2
    extra_curves = curve_paths2 - curve_paths1
    common_curves = curve_paths1 & curve_paths2

    if missing_curves:
        print(f"\n  Curves missing in File 2 ({len(missing_curves)}):")
        for path in sorted(missing_curves)[:5]:
            print(f"    - {path}")
        if len(missing_curves) > 5:
            print(f"    ... and {len(missing_curves) - 5} more")

    if extra_curves:
        print(f"\n  Extra curves in File 2 ({len(extra_curves)}):")
        for path in sorted(extra_curves)[:5]:
            print(f"    + {path}")
        if len(extra_curves) > 5:
            print(f"    ... and {len(extra_curves) - 5} more")

    # Compare common curves
    print(f"\n  Comparing {len(common_curves)} common curves...")

    curve_diff_count = 0
    for path in sorted(common_curves):
        curve1 = curves1[path]
        curve2 = curves2[path]

        curve_diffs = []

        # Compare geometry
        curve_diffs.extend(compare_curve_geometry(curve1, curve2))

        # Compare arbGeomParams
        curve_diffs.extend(compare_arb_geom_params(curve1, curve2))

        # Compare userProperties
        curve_diffs.extend(compare_user_properties(curve1, curve2))

        if curve_diffs:
            curve_diff_count += 1
            if curve_diff_count <= 5:  # Only show first 5
                print(f"\n  Curve '{path}' has differences:")
                for diff in curve_diffs:
                    print(diff)
                all_differences.append(f"Curve '{path}': {len(curve_diffs)} differences")

    if curve_diff_count == 0:
        print("  All common curves are IDENTICAL")
    elif curve_diff_count > 5:
        print(f"\n  ... and {curve_diff_count - 5} more curves with differences")

    # -------------------------------------------------------------------------
    # 4. Compare Xform objects
    # -------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("4. XFORM OBJECT COMPARISON")
    print("-" * 70)

    xforms1 = {}
    xforms2 = {}

    collect_objects(archive1.top, xforms1, "Xform")
    collect_objects(archive2.top, xforms2, "Xform")

    print(f"\nTotal Xforms in File 1: {len(xforms1)}")
    print(f"Total Xforms in File 2: {len(xforms2)}")

    xform_paths1 = set(xforms1.keys())
    xform_paths2 = set(xforms2.keys())

    missing_xforms = xform_paths1 - xform_paths2
    extra_xforms = xform_paths2 - xform_paths1

    if missing_xforms:
        print(f"\n  Xforms missing in File 2 ({len(missing_xforms)}):")
        for path in sorted(missing_xforms):
            print(f"    - {path}")

    if extra_xforms:
        print(f"\n  Extra Xforms in File 2 ({len(extra_xforms)}):")
        for path in sorted(extra_xforms):
            print(f"    + {path}")

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if all_differences:
        print(f"\nTotal differences found: {len(all_differences)}")
        print("\nAll differences:")
        for i, diff in enumerate(all_differences, 1):
            print(f"  {i}. {diff}")
    else:
        print("\nNO DIFFERENCES FOUND - Files are identical!")

    print("\n" + "=" * 70)


def inspect_groom_root_uv(file_path, fps=24):
    """
    Inspect groom_root_uv metadata in a single ABC file.

    :param file_path: path to .abc file
    :param fps: frames per second
    """
    print("=" * 70)
    print("INSPECT groom_root_uv")
    print("=" * 70)
    print(f"\nFile: {file_path}")

    try:
        archive = cask.Archive(file_path, fps=fps)
        print(f"Loaded: {archive}")
    except Exception as e:
        print(f"ERROR loading file: {e}")
        return

    # Collect all curves
    curves = {}
    collect_objects(archive.top, curves, "Curve")

    print(f"\nTotal curves found: {len(curves)}")

    for path, curve in sorted(curves.items()):
        geom = curve.properties.get('.geom')
        if not geom:
            continue

        arb = geom.properties.get('.arbGeomParams')
        if not arb:
            continue

        groom_root_uv = arb.properties.get('groom_root_uv')
        if groom_root_uv:
            meta = dict(groom_root_uv.metadata) if hasattr(groom_root_uv, 'metadata') else {}
            interpretation = meta.get('interpretation', 'N/A')
            print(f"\n  Curve: {path}")
            print(f"    interpretation: '{interpretation}'")
            print(f"    full metadata: {meta}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--inspect':
        # Inspect single file mode
        file_path = sys.argv[2] if len(sys.argv) > 2 else "/path/to/CHARACTER/MyCharacter/abc/strands_applying_texture.abc"
        inspect_groom_root_uv(file_path, fps=30)
    else:
        # Compare mode (default)
        file1 = "/path/to/CHARACTER/MyCharacter/abc/groom_from_glm.abc"
        file2 = "/path/to/CHARACTER/MyCharacter/abc/groom_from_opus.abc"
        compare_archives(file1, file2, fps=30)
