import sys
import os

# Add the path to cask.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import cask


def check_riCurves_attribute(abc_file):
    """
    Check if riCurves attribute exists on objects in the ABC file.
    The riCurves bool attribute is added in Maya to force curves to be exported as one group.

    Args:
        abc_file (str): Path to the ABC file

    Returns:
        dict: Dictionary with results showing which objects have riCurves
    """
    if not os.path.exists(abc_file):
        print(f"Error: File not found: {abc_file}")
        return {}

    print(f"\n{'='*80}")
    print(f"Checking for riCurves attribute")
    print(f"ABC File: {abc_file}")
    print(f"{'='*80}\n")

    archive = cask.Archive(abc_file)
    all_objects = cask.find(archive.top)

    if not all_objects:
        print("No objects found in the ABC file.")
        return {}

    print(f"Total objects in file: {len(all_objects)}\n")

    results = {
        'with_riCurves': [],
        'without_riCurves': [],
        'details': {}
    }

    # Check each object for riCurves attribute
    for obj in all_objects:
        has_riCurves = False
        riCurves_value = None
        riCurves_location = None

        try:
            properties = obj.properties

            # Check in top-level properties
            if 'riCurves' in properties:
                has_riCurves = True
                riCurves_location = 'top-level'
                try:
                    prop = properties['riCurves']
                    if hasattr(prop, 'iobject') and prop.iobject:
                        if prop.iobject.getNumSamples() > 0:
                            riCurves_value = prop.get_value(0)
                except:
                    pass

            # Check under .geom property
            if not has_riCurves and '.geom' in properties:
                geom_prop = properties['.geom']
                geom_sub_props = geom_prop.properties

                if 'riCurves' in geom_sub_props:
                    has_riCurves = True
                    riCurves_location = '.geom'
                    try:
                        prop = geom_sub_props['riCurves']
                        if hasattr(prop, 'iobject') and prop.iobject:
                            if prop.iobject.getNumSamples() > 0:
                                riCurves_value = prop.get_value(0)
                    except:
                        pass

            # Check under .geom/.arbGeomParams
            if not has_riCurves and '.geom' in properties:
                geom_prop = properties['.geom']
                geom_sub_props = geom_prop.properties

                if '.arbGeomParams' in geom_sub_props:
                    arb_prop = geom_sub_props['.arbGeomParams']
                    arb_sub_props = arb_prop.properties

                    if 'riCurves' in arb_sub_props:
                        has_riCurves = True
                        riCurves_location = '.geom/.arbGeomParams'
                        try:
                            prop = arb_sub_props['riCurves']
                            if hasattr(prop, 'iobject') and prop.iobject:
                                if prop.iobject.getNumSamples() > 0:
                                    riCurves_value = prop.get_value(0)
                        except:
                            pass

            obj_info = {
                'name': obj.name,
                'type': obj.type(),
                'path': obj.path(),
                'has_riCurves': has_riCurves,
                'riCurves_value': riCurves_value,
                'riCurves_location': riCurves_location
            }

            results['details'][obj.name] = obj_info

            if has_riCurves:
                results['with_riCurves'].append(obj.name)
            else:
                results['without_riCurves'].append(obj.name)

        except Exception as e:
            print(f"Error checking {obj.name}: {e}")

    # Print results
    print(f"{'─'*80}")
    print(f"SUMMARY")
    print(f"{'─'*80}")
    print(f"✓ Objects WITH riCurves:    {len(results['with_riCurves'])}")
    print(f"✗ Objects WITHOUT riCurves: {len(results['without_riCurves'])}")
    print(f"{'─'*80}\n")

    # Show objects with riCurves
    if results['with_riCurves']:
        print(f"{'='*80}")
        print(f"OBJECTS WITH riCurves ATTRIBUTE ({len(results['with_riCurves'])})")
        print(f"{'='*80}\n")

        for obj_name in results['with_riCurves']:
            info = results['details'][obj_name]
            print(f"✓ {info['name']}")
            print(f"  Type: {info['type']}")
            print(f"  Path: {info['path']}")
            print(f"  Location: {info['riCurves_location']}")
            print(f"  Value: {info['riCurves_value']}")
            print()
    else:
        print("❌ NO objects have the riCurves attribute!\n")

    # Show objects without riCurves (first 20)
    if results['without_riCurves']:
        print(f"{'='*80}")
        print(f"OBJECTS WITHOUT riCurves ATTRIBUTE ({len(results['without_riCurves'])})")
        print(f"{'='*80}\n")

        for obj_name in results['without_riCurves'][:20]:
            info = results['details'][obj_name]
            print(f"✗ {info['name']} ({info['type']}) - {info['path']}")

        if len(results['without_riCurves']) > 20:
            print(f"\n  ... and {len(results['without_riCurves']) - 20} more objects without riCurves")
        print()

    # Final verdict
    print(f"{'='*80}")
    print(f"VERDICT")
    print(f"{'='*80}")

    total_curves = sum(1 for obj in all_objects if obj.type() == 'Curve')
    curves_with_riCurves = sum(1 for name in results['with_riCurves']
                                if results['details'][name]['type'] == 'Curve')

    print(f"Total Curve objects: {total_curves}")
    print(f"Curves with riCurves: {curves_with_riCurves}")

    if total_curves > 0:
        if curves_with_riCurves == total_curves:
            print(f"\n✓✓✓ SUCCESS! All curves have the riCurves attribute!")
        elif curves_with_riCurves > 0:
            print(f"\n⚠ WARNING: Only {curves_with_riCurves}/{total_curves} curves have riCurves")
        else:
            print(f"\n❌ ERROR: None of the curves have riCurves attribute!")
            print(f"\nPossible reasons:")
            print(f"  1. The attribute wasn't added in Maya before export")
            print(f"  2. The export command didn't include the attribute")
            print(f"  3. The attribute name might be different (check spelling)")

    print(f"{'='*80}\n")

    return results


def list_geom_attributes_for_spline_descriptions(abc_file):
    """
    List all sub-attributes under the .geom property for objects with names
    ending in '_splineDescription'. This is useful for inspecting groom_* attributes.

    Args:
        abc_file (str): Path to the ABC file

    Returns:
        dict: Dictionary mapping object names to their geom sub-attributes
    """
    if not os.path.exists(abc_file):
        print(f"Error: File not found: {abc_file}")
        return {}

    print(f"\nSearching for *_splineDescription objects in: {abc_file}")
    print("=" * 80)

    archive = cask.Archive(abc_file)
    # archive.write_to_file("/path/to/output/b.abc")
    # Find all objects (curves and others)
    all_objects = cask.find(archive.top)

    # Filter objects ending with _splineDescription
    spline_objects = [obj for obj in all_objects]# if obj.name.endswith('_splineDescription')]

    if not spline_objects:
        print("No objects with names ending in '_splineDescription' found.")
        return {}

    print(f"\nFound {len(spline_objects)} object(s) ending with '_splineDescription':\n")

    result = {}

    for i, obj in enumerate(spline_objects, 1):
        print(f"\n{i}. Object: {obj.name}")
        print(f"   Type: {obj.type()}")
        print(f"   Path: {obj.path()}")
        # curve_child._iobject._parent = output_archive.top
        print('       Archive   ', obj._iobject.getArchive())
        print('       FullName   ', obj._iobject.getFullName())
        print('       Header   ', obj._iobject.getHeader())
        print('       MetaData   ', obj._iobject.getMetaData())
        print('       Name   ', obj._iobject.getName())
        print('       Parent   ', obj._iobject.getParent())
        # Look for .geom property
        try:
            properties = obj.properties

            if '.geom' in properties:
                geom_prop = properties['.geom']
                print(f"   ✓ Found .geom property")

                # Get sub-properties under .geom
                geom_sub_props = geom_prop.properties

                if geom_sub_props and len(geom_sub_props) > 0:
                    print(f"   .geom sub-attributes ({len(geom_sub_props)}):")

                    sub_attrs = {}

                    for prop_name, prop in geom_sub_props.items():
                        try:
                            prop_info = {
                                'name': prop_name,
                                'is_compound': False,
                                'type': None,
                                'value': None
                            }

                            # Determine if compound or simple
                            if hasattr(prop, 'iobject') and prop.iobject:
                                is_compound = prop.is_compound()
                                prop_info['is_compound'] = is_compound

                                if is_compound:
                                    sub_count = len(prop.properties) if prop.properties else 0
                                    print(f"      • {prop_name} [Compound] ({sub_count} sub-properties)")
                                    prop_info['sub_count'] = sub_count

                                    # List sub-properties of compound
                                    if sub_count > 0:
                                        for sub_name in prop.properties.keys():
                                            print(f"          - {sub_name}")
                                else:
                                    # Simple property - get type and value
                                    try:
                                        is_scalar = prop.iobject.isScalar()
                                        prop_type = "Scalar" if is_scalar else "Array"
                                        prop_info['type'] = prop_type

                                        # Get data type
                                        dt = prop.iobject.getDataType()
                                        pod = str(dt.getPod())
                                        prop_info['pod'] = pod

                                        # Get value if available
                                        if prop.iobject.getNumSamples() > 0:
                                            val = prop.get_value(0)
                                            val_str = str(val)
                                            if len(val_str) > 80:
                                                val_str = val_str[:80] + "..."
                                            prop_info['value'] = val_str
                                            print(f"      • {prop_name} [{prop_type}] {pod} = {val_str}")
                                        else:
                                            print(f"      • {prop_name} [{prop_type}] {pod} (no samples)")
                                    except Exception as e:
                                        print(f"      • {prop_name} [Error reading details: {e}]")
                            else:
                                print(f"      • {prop_name} [No iobject]")

                            sub_attrs[prop_name] = prop_info

                        except Exception as e:
                            print(f"      • {prop_name} [Error: {e}]")

                    result[obj.name] = sub_attrs
                else:
                    print(f"   .geom has no sub-attributes")
                    result[obj.name] = {}
            else:
                print(f"   ✗ No .geom property found")
                print(f"   Available properties: {list(properties.keys())[:10]}")
                result[obj.name] = None

        except Exception as e:
            print(f"   Error reading properties: {e}")
            result[obj.name] = None

        print("-" * 80)

    print(f"\n{'='*80}")
    print(f"Summary: Found {len(spline_objects)} *_splineDescription object(s)")

    # Summary of groom_* attributes found
    groom_attrs = set()
    for obj_name, attrs in result.items():
        if attrs:
            for attr_name in attrs.keys():
                if attr_name.startswith('groom_'):
                    groom_attrs.add(attr_name)

    if groom_attrs:
        print(f"\nFound {len(groom_attrs)} groom_* attribute(s):")
        for attr in sorted(groom_attrs):
            print(f"  • {attr}")
    else:
        print("\nNo groom_* attributes found under .geom properties")

    print("=" * 80)

    return result


def print_frame_range(abc_file):
    """
    Print the start and end frame stored in an Alembic file.

    Args:
        abc_file (str): Path to the ABC file
    """
    if not os.path.exists(abc_file):
        print(f"Error: File not found: {abc_file}")
        return

    archive = cask.Archive(abc_file, fps=30)

    start_frame = archive.start_frame()
    end_frame = archive.end_frame()
    start_time = archive.start_time()
    end_time = archive.end_time()
    fps = archive.fps

    print(f"\nABC File: {abc_file}")
    print(f"  FPS:         {fps}")
    print(f"  Start Frame: {start_frame}")
    print(f"  End Frame:   {end_frame}")
    print(f"  Start Time:  {start_time:.4f}s")
    print(f"  End Time:    {end_time:.4f}s")

    # Show time sampling details
    for i, ts in enumerate(archive.timesamplings):
        tst = ts.getTimeSamplingType()
        num_stored = ts.getNumStoredTimes()
        print(f"\n  TimeSampling[{i}]:")
        print(f"    Stored times: {num_stored}")
        print(f"    Uniform: {tst.isUniform()}, Cyclic: {tst.isCyclic()}, Acyclic: {tst.isAcyclic()}")
        if num_stored > 0:
            print(f"    First sample time: {ts.getSampleTime(0):.4f}s")
            if num_stored > 1:
                print(f"    Last sample time:  {ts.getSampleTime(num_stored - 1):.4f}s")

    return (start_frame, end_frame)


def print_all_curves(abc_file):
    """
    Print all Curve objects in an Alembic file.

    Args:
        abc_file (str): Path to the ABC file
    """
    return print_all_objects(abc_file, types=["Curve"])


def print_all_objects(abc_file, types=None, show_properties=True):
    """
    Print all objects in an Alembic file with their attributes.

    Args:
        abc_file (str): Path to the ABC file
        types (list): List of object types to filter (e.g., ["Curve", "PolyMesh"]).
                      None means all types.
        show_properties (bool): Whether to show properties/attributes

    Returns:
        list: List of objects found
    """
    if not os.path.exists(abc_file):
        print(f"Error: File not found: {abc_file}")
        return []

    print(f"Opening ABC file: {abc_file}")
    print("=" * 80)
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

    print(f"\nFound {len(objects)} object(s) of {len(objects_by_type)} type(s):\n")
    for obj_type, count in sorted([(t, len(o)) for t, o in objects_by_type.items()]):
        print(f"  - {obj_type}: {count}")
    print("\n" + "=" * 80)

    # Print detailed information for each object
    for i, obj in enumerate(objects, 1):
        print(f"\n{i}. Object Name: {obj.name}")
        print(f"   Type: {obj.type()}")
        print(f"   Full Path: {obj.path()}")

        # Print metadata if available
        if hasattr(obj, 'metadata') and obj.metadata:
            print(f"   Metadata: {dict(obj.metadata)}")

        # Print geometry-specific information
        if obj.type() == "Curve":
            _print_curve_info(obj)
        elif obj.type() == "PolyMesh":
            _print_polymesh_info(obj)
        elif obj.type() == "Points":
            _print_points_info(obj)
        elif obj.type() == "Xform":
            _print_xform_info(obj)
        else:
            _print_generic_geometry_info(obj)

        # Print properties/attributes
        if show_properties:
            _print_properties(obj)

        print("-" * 80)

    print(f"\nTotal: {len(objects)} object(s) found.")
    return objects


def _print_curve_info(curve):
    """Print Curve-specific information."""
    if curve.iobject:
        try:
            import alembic
            icurves = alembic.AbcGeom.ICurves(curve.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
            schema = icurves.getSchema()
            num_samples = schema.getNumSamples()
            print(f"   Samples: {num_samples}")

            if num_samples > 0:
                sample = schema.getValue(0)
                num_curves = sample.getNumCurves()
                positions = sample.getPositions()
                num_verts = sample.getCurvesNumVertices()

                print(f"   Curve Count: {num_curves}")
                print(f"   Total Vertices: {len(positions)}")
                if num_verts:
                    vert_list = list(num_verts)
                    print(f"   Vertices per Curve (first 10): {vert_list[:10]}{'...' if len(num_verts) > 10 else ''}")
        except Exception as e:
            print(f"   Error reading curve data: {e}")


def _print_polymesh_info(mesh):
    """Print PolyMesh-specific information."""
    if mesh.iobject:
        try:
            import alembic
            imesh = alembic.AbcGeom.IPolyMesh(mesh.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
            schema = imesh.getSchema()
            num_samples = schema.getNumSamples()
            print(f"   Samples: {num_samples}")

            if num_samples > 0:
                sample = schema.getValue()
                positions = sample.getPositions()
                face_counts = sample.getFaceCounts()
                face_indices = sample.getFaceIndices()

                print(f"   Vertex Count: {len(positions)}")
                print(f"   Face Count: {len(face_counts)}")
                print(f"   Face Indices Count: {len(face_indices)}")
        except Exception as e:
            print(f"   Error reading polymesh data: {e}")


def _print_points_info(points):
    """Print Points-specific information."""
    if points.iobject:
        try:
            import alembic
            ipoints = alembic.AbcGeom.IPoints(points.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
            schema = ipoints.getSchema()
            num_samples = schema.getNumSamples()
            print(f"   Samples: {num_samples}")

            if num_samples > 0:
                sample = schema.getValue()
                positions = sample.getPositions()
                print(f"   Point Count: {len(positions)}")
        except Exception as e:
            print(f"   Error reading points data: {e}")


def _print_xform_info(xform):
    """Print Xform-specific information."""
    if xform.iobject:
        try:
            import alembic
            ixform = alembic.AbcGeom.IXform(xform.iobject, alembic.Abc.WrapExistingFlag.kWrapExisting)
            schema = ixform.getSchema()
            num_samples = schema.getNumSamples()
            print(f"   Samples: {num_samples}")

            if num_samples > 0:
                sample = schema.getValue()
                # Print transform info if available
                print(f"   Has Transform: Yes")
        except Exception as e:
            print(f"   Error reading xform data: {e}")


def _print_generic_geometry_info(obj):
    """Print generic geometry information for unknown types."""
    if obj.iobject:
        try:
            import alembic
            # Try to get basic schema info
            print(f"   Has IObject: Yes")
        except Exception as e:
            print(f"   Error reading object data: {e}")


def _print_properties(obj):
    """Print all properties/attributes of an object."""
    try:
        properties = obj.properties
        if properties and len(properties) > 0:
            print(f"   Properties ({len(properties)}):")
            for prop_name, prop in list(properties.items())[:20]:  # Limit to first 20
                try:
                    prop_info = f"      - {prop_name}"

                    # Add type information
                    if hasattr(prop, 'iobject') and prop.iobject:
                        if prop.is_compound():
                            prop_info += " [Compound]"
                        else:
                            # Try to get value info
                            try:
                                if prop.iobject.isScalar():
                                    prop_info += " [Scalar]"
                                else:
                                    prop_info += " [Array]"

                                # Get data type
                                dt = prop.iobject.getDataType()
                                prop_info += f" - {dt.getPod()}"

                                # Get first value if available
                                if prop.iobject.getNumSamples() > 0:
                                    val = prop.get_value(0)
                                    val_str = str(val)
                                    if len(val_str) > 60:
                                        val_str = val_str[:60] + "..."
                                    prop_info += f" = {val_str}"
                            except:
                                pass

                    print(prop_info)
                except Exception as e:
                    print(f"      - {prop_name} [Error: {e}]")

            if len(properties) > 20:
                print(f"      ... and {len(properties) - 20} more properties")
        else:
            print(f"   Properties: None")
    except Exception as e:
        print(f"   Error reading properties: {e}")


# abc_file = "/path/to/your/groom.abc"
# abc_file = "/path/to/your/test.abc"
# abc_file = "/path/to/your/strands_with_attr.abc"
# abc_file = "/path/to/your/groom_correct.abc"
# abc_file = "/path/to/your/groom_with_userprops.abc"
# abc_file = "/path/to/your/applying_texture.abc"
abc_file = "/path/to/your/groom.abc"


if __name__ == "__main__":
    # NEW: List all sub-attributes under .geom for *_splineDescription objects
    # This will show groom_* attributes
    # geom_attrs = list_geom_attributes_for_spline_descriptions(abc_file)

    # Example usage - print all objects (not just curves) with their attributes
    # objects = print_all_objects(abc_file)

    # Or print only curves
    # curves = print_all_curves(abc_file)

    # Or print specific types
    # meshes = print_all_objects(abc_file, types=["PolyMesh"])

    # Or print without properties (faster)
    # objects = print_all_objects(abc_file, show_properties=False)

    # Check riCurves attribute
    # check_riCurves_attribute(abc_file)

    # Print start/end frame range
    print_frame_range(abc_file)
