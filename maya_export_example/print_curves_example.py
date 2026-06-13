"""
Example script to print all curves from an Alembic file.
This demonstrates various ways to extract and display curve information.
Updated to support all object types and their attributes.
"""

import sys
import os
import cask


def print_all_objects(abc_file, types=None, show_properties=True, max_objects=None):
    """
    Print all objects in an Alembic file with their attributes.

    Args:
        abc_file (str): Path to the ABC file
        types (list): List of object types to filter (e.g., ["Curve", "PolyMesh"]).
                      None means all types.
        show_properties (bool): Whether to show properties/attributes
        max_objects (int): Maximum number of objects to display in detail (None for all)

    Returns:
        list: List of objects found
    """
    if not os.path.exists(abc_file):
        print(f"Error: File not found: {abc_file}")
        return []

    print(f"\n{'='*80}")
    print(f"ABC FILE: {abc_file}")
    print(f"{'='*80}")

    archive = cask.Archive(abc_file)

    # Find all objects (or filter by types)
    objects = cask.find(archive.top, types=types) if types else cask.find(archive.top)

    if not objects:
        print(f"No objects found in the ABC file.")
        return []

    # Group objects by type
    objects_by_type = {}
    for obj in objects:
        obj_type = obj.type()
        if obj_type not in objects_by_type:
            objects_by_type[obj_type] = []
        objects_by_type[obj_type].append(obj)

    print(f"\nFound {len(objects)} object(s) of {len(objects_by_type)} type(s):")
    for obj_type, objs in sorted(objects_by_type.items()):
        print(f"  - {obj_type}: {len(objs)}")
    print(f"\n{'='*80}\n")

    # Print detailed information for each object
    for i, obj in enumerate(objects, 1):
        if max_objects and i > max_objects:
            print(f"... and {len(objects) - max_objects} more objects (use max_objects=None to see all)")
            break

        print(f"\nOBJECT #{i}")
        print(f"  Name: {obj.name}")
        print(f"  Type: {obj.type()}")
        print(f"  Path: {obj.path()}")

        # Print metadata if available
        if hasattr(obj, 'metadata') and obj.metadata:
            print(f"  Metadata: {dict(obj.metadata)}")

        # Print type-specific geometry information
        _print_geometry_info(obj)

        # Print properties/attributes
        if show_properties:
            _print_object_properties(obj)

        print("-" * 80)

    print(f"\nTotal: {len(objects)} object(s) found.")
    return objects


def _print_geometry_info(obj):
    """Print geometry-specific information based on object type."""
    if not obj.iobject:
        return

    try:
        import alembic
        obj_type = obj.type()

        if obj_type == "Curve":
            icurves = alembic.AbcGeom.ICurves(obj.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
            schema = icurves.getSchema()
            num_samples = schema.getNumSamples()
            print(f"  Samples: {num_samples}")

            if num_samples > 0:
                sample = schema.getValue(0)
                num_curves = sample.getNumCurves()
                positions = sample.getPositions()
                num_verts = sample.getCurvesNumVertices()

                print(f"  Curve Count: {num_curves}")
                print(f"  Total Vertices: {len(positions)}")
                if num_verts:
                    vert_list = list(num_verts)
                    print(f"  Vertices per Curve (first 10): {vert_list[:10]}{'...' if len(num_verts) > 10 else ''}")

        elif obj_type == "PolyMesh":
            imesh = alembic.AbcGeom.IPolyMesh(obj.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
            schema = imesh.getSchema()
            num_samples = schema.getNumSamples()
            print(f"  Samples: {num_samples}")

            if num_samples > 0:
                sample = schema.getValue()
                positions = sample.getPositions()
                face_counts = sample.getFaceCounts()

                print(f"  Vertex Count: {len(positions)}")
                print(f"  Face Count: {len(face_counts)}")

        elif obj_type == "Points":
            ipoints = alembic.AbcGeom.IPoints(obj.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
            schema = ipoints.getSchema()
            num_samples = schema.getNumSamples()
            print(f"  Samples: {num_samples}")

            if num_samples > 0:
                sample = schema.getValue()
                positions = sample.getPositions()
                print(f"  Point Count: {len(positions)}")

        elif obj_type == "Xform":
            ixform = alembic.AbcGeom.IXform(obj.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
            schema = ixform.getSchema()
            num_samples = schema.getNumSamples()
            print(f"  Samples: {num_samples}")
            print(f"  Has Transform: Yes")

        else:
            print(f"  Geometry Type: {obj_type}")

    except Exception as e:
        print(f"  Error reading geometry data: {e}")


def _print_object_properties(obj):
    """Print all properties/attributes of an object."""
    try:
        properties = obj.properties
        if properties and len(properties) > 0:
            print(f"  Properties ({len(properties)}):")
            for prop_name, prop in list(properties.items())[:15]:  # Limit to first 15
                try:
                    prop_info = f"    • {prop_name}"

                    if hasattr(prop, 'iobject') and prop.iobject:
                        if prop.is_compound():
                            prop_info += " [Compound]"
                            # Show sub-properties
                            if len(prop.properties) > 0:
                                prop_info += f" ({len(prop.properties)} sub-properties)"
                        else:
                            # Get property type and value
                            try:
                                if prop.iobject.isScalar():
                                    prop_info += " [Scalar]"
                                else:
                                    prop_info += " [Array]"

                                # Get first value if available
                                if prop.iobject.getNumSamples() > 0:
                                    val = prop.get_value(0)
                                    val_str = str(val)
                                    if len(val_str) > 50:
                                        val_str = val_str[:50] + "..."
                                    prop_info += f" = {val_str}"
                            except:
                                pass

                    print(prop_info)
                except Exception as e:
                    print(f"    • {prop_name} [Error: {e}]")

            if len(properties) > 15:
                print(f"    ... and {len(properties) - 15} more properties")
        else:
            print(f"  Properties: None")
    except Exception as e:
        print(f"  Error reading properties: {e}")


def print_all_curves_basic(abc_file):
    """
    Basic function to print all Curve objects in an Alembic file.

    Args:
        abc_file (str): Path to the ABC file

    Returns:
        list: List of Curve objects found
    """
    if not os.path.exists(abc_file):
        print(f"Error: File not found: {abc_file}")
        return []

    print(f"Opening ABC file: {abc_file}")
    archive = cask.Archive(abc_file)

    # Find all Curve objects in the archive
    curves = cask.find(archive.top, types=["Curve"])

    if not curves:
        print("No curves found in the ABC file.")
        return []

    print(f"\nFound {len(curves)} curve(s):\n")
    print("-" * 80)

    for i, curve in enumerate(curves, 1):
        print(f"{i}. Curve Name: {curve.name}")
        print(f"   Full Path: {curve.path()}")

        # Get schema if available
        if curve.iobject:
            try:
                import alembic
                icurves = alembic.AbcGeom.ICurves(curve.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
                schema = icurves.getSchema()
                num_samples = schema.getNumSamples()
                print(f"   Number of Samples: {num_samples}")

                # Get info from first sample if available
                if num_samples > 0:
                    sample = schema.getValue(0)
                    num_curves = sample.getNumCurves()
                    positions = sample.getPositions()
                    num_verts = sample.getCurvesNumVertices()

                    print(f"   Number of Curves in Object: {num_curves}")
                    print(f"   Total Vertex Count: {len(positions)}")
                    if num_verts:
                        vert_list = list(num_verts)
                        print(f"   Vertices per Curve: {vert_list[:10]}{'...' if len(num_verts) > 10 else ''}")
            except Exception as e:
                print(f"   Error reading curve data: {e}")

        print("-" * 80)

    return curves


def print_all_curves_detailed(abc_file, show_positions=False, max_curves=None):
    """
    Detailed function to print all Curve objects with more information.

    Args:
        abc_file (str): Path to the ABC file
        show_positions (bool): Whether to show vertex positions (can be verbose)
        max_curves (int): Maximum number of curves to display in detail (None for all)

    Returns:
        list: List of Curve objects found
    """
    if not os.path.exists(abc_file):
        print(f"Error: File not found: {abc_file}")
        return []

    archive = cask.Archive(abc_file)
    curves = cask.find(archive.top, types=["Curve"])

    if not curves:
        print("No curves found in the ABC file.")
        return []

    print(f"\n{'='*80}")
    print(f"ABC FILE: {abc_file}")
    print(f"Total Curves Found: {len(curves)}")
    print(f"{'='*80}\n")

    for i, curve in enumerate(curves, 1):
        if max_curves and i > max_curves:
            print(f"... and {len(curves) - max_curves} more curves (use max_curves=None to see all)")
            break

        print(f"\nCURVE #{i}")
        print(f"  Name: {curve.name}")
        print(f"  Path: {curve.path()}")
        print(f"  Type: {curve.type()}")

        # Get schema if available
        if curve.iobject:
            try:
                import alembic
                icurves = alembic.AbcGeom.ICurves(curve.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
                schema = icurves.getSchema()
                num_samples = schema.getNumSamples()
                print(f"  Samples: {num_samples}")

                # Get info from first sample
                if num_samples > 0:
                    sample = schema.getValue(0)
                    num_curves = sample.getNumCurves()
                    positions = sample.getPositions()
                    num_verts = sample.getCurvesNumVertices()

                    print(f"  Curve Count: {num_curves}")
                    print(f"  Total Vertices: {len(positions)}")

                    if num_verts:
                        vert_list = list(num_verts)
                        print(f"  Min Vertices per Curve: {min(vert_list)}")
                        print(f"  Max Vertices per Curve: {max(vert_list)}")
                        print(f"  Avg Vertices per Curve: {sum(vert_list) / len(vert_list):.2f}")

                    # Show vertex positions if requested
                    if show_positions and positions:
                        print(f"  First 5 Vertex Positions:")
                        for j, pos in enumerate(list(positions)[:5]):
                            print(f"    [{j}]: ({pos.x:.4f}, {pos.y:.4f}, {pos.z:.4f})")
                        if len(positions) > 5:
                            print(f"    ... and {len(positions) - 5} more vertices")
            except Exception as e:
                print(f"  Error reading curve data: {e}")

        print("-" * 80)

    return curves


def print_curve_hierarchy(abc_file):
    """
    Print the hierarchy of the ABC file showing where curves are located.

    Args:
        abc_file (str): Path to the ABC file
    """
    if not os.path.exists(abc_file):
        print(f"Error: File not found: {abc_file}")
        return

    archive = cask.Archive(abc_file)

    def print_tree(obj, indent=0):
        """Recursively print the object hierarchy."""
        prefix = "  " * indent
        obj_type = obj.type()
        marker = " [CURVE]" if obj_type == "Curve" else ""
        print(f"{prefix}├─ {obj.name} ({obj_type}){marker}")

        for child in obj.children.values():
            print_tree(child, indent + 1)

    print(f"\nHierarchy of ABC file: {abc_file}\n")
    print_tree(archive.top)


if __name__ == "__main__":
    # Example usage - replace with your ABC file path
    abc_file = "path/to/your/file.abc"

    # Uncomment the function you want to test:

    # NEW: Print all objects (any type) with attributes
    # objects = print_all_objects(abc_file)

    # Print only specific types with attributes
    # curves = print_all_objects(abc_file, types=["Curve"])
    # meshes = print_all_objects(abc_file, types=["PolyMesh", "SubD"])

    # Print without attributes (faster)
    # objects = print_all_objects(abc_file, show_properties=False)

    # Basic curve usage
    # curves = print_all_curves_basic(abc_file)

    # Detailed curve usage
    # curves = print_all_curves_detailed(abc_file, show_positions=True, max_curves=5)

    # Show hierarchy
    # print_curve_hierarchy(abc_file)

    # Usage with command line argument
    if len(sys.argv) > 1:
        abc_file = sys.argv[1]
        # Use the new comprehensive function
        print_all_objects(abc_file, show_properties=True, max_objects=10)
    else:
        print("Usage: python print_curves_example.py <path_to_abc_file>")
        print("\nOr edit the script and uncomment one of the maya_export_example function calls.")



