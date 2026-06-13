#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os

# Add the path to Qt.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from Qt import QtWidgets, QtCore
from maya import cmds
import maya.OpenMayaUI as OpenMayaUI
from shiboken2 import wrapInstance

from export_xgen_strands_and_guides import (
    get_description_mesh_map,
    convert_to_interactive_groom,
    export_interactive_groom,
    create_guide_attributes,
    export_group,
    rollback_guide_attributes,
)
from write_xgen_abc_attrs import merge_and_process_abc
import json


def get_maya_main_window():
    ptr = OpenMayaUI.MQtUtil.mainWindow()
    if ptr is not None:
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    return None


def check_save_changes():
    """Check if the current Maya scene has been saved.

    Returns:
        bool: True if the scene has been saved, False otherwise.
    """
    # Check if current file has unsaved changes, prompt user to save
    if cmds.file(query=True, modified=True):
        # Use Maya's native save prompt (Save/Don't Save/Cancel)
        result = cmds.confirmDialog(
            title='Save Changes',
            message='Save changes to {}?'.format(
                cmds.file(query=True, sceneName=True) or 'untitled'
            ),
            button=['Save', "Don't Save", 'Cancel'],
            defaultButton='Save',
            cancelButton='Cancel',
            dismissString='Cancel'
        )
        if result == 'Save':
            cmds.file(save=True, force=True)
        elif result == 'Cancel':
            return False
    return True


class XGenExportTool(QtWidgets.QWidget):

    WINDOW_TITLE = "XGen Export Tool"
    OBJECT_NAME = "XGenExportToolWindow"

    def __init__(self, parent=None):
        super(XGenExportTool, self).__init__(parent)
        self.setObjectName(self.OBJECT_NAME)
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setWindowFlags(QtCore.Qt.Window)
        self.setMinimumWidth(680)
        self._build_ui()
        self.dir_edit.setText(self._get_default_export_dir())

    def _get_default_export_dir(self):
        scene_path = cmds.file(q=True, sceneName=True)
        if not scene_path:
            return ""
        scene_path = scene_path.replace("\\", "/")
        if "/assets/" in scene_path.lower():
            # <root>/assets/<type>/<name>/<department>/file.mb -> <root>/assets/<type>/<name>/XGEN/
            assets_idx = scene_path.lower().index("/assets/")
            after_assets = scene_path[assets_idx + len("/assets/"):]
            parts = after_assets.split("/")
            if len(parts) >= 3:
                root = scene_path[:assets_idx]
                return "{}/assets/{}/{}/XGEN/".format(root, parts[0], parts[1])
        elif "/scenes/" in scene_path.lower():
            # <root>/scenes/<sea>/<ep>/<scene>/<shot>/file.mb -> same dir + xgen/
            scenes_idx = scene_path.lower().index("/scenes/")
            after_scenes = scene_path[scenes_idx + len("/scenes/"):]
            parts = after_scenes.split("/")
            if len(parts) >= 5:
                root = scene_path[:scenes_idx]
                return "{}/scenes/{}/{}/{}/{}/xgen/".format(
                    root, parts[0], parts[1], parts[2], parts[3]
                )
        return ""

    def _build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        # -- Export Directory --
        dir_layout = QtWidgets.QHBoxLayout()
        dir_layout.addWidget(QtWidgets.QLabel("Export Dir:"))
        self.dir_edit = QtWidgets.QLineEdit()
        self.dir_edit.setPlaceholderText("Select export directory...")
        dir_layout.addWidget(self.dir_edit)
        browse_btn = QtWidgets.QPushButton("...")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self._browse_export_dir)
        dir_layout.addWidget(browse_btn)
        main_layout.addLayout(dir_layout)

        # -- Guide Settings --
        guide_layout = QtWidgets.QHBoxLayout()
        guide_layout.addWidget(QtWidgets.QLabel("Guide Root:"))
        self.guide_root_edit = QtWidgets.QLineEdit("guides")
        guide_layout.addWidget(self.guide_root_edit)
        guide_layout.addWidget(QtWidgets.QLabel("Suffix:"))
        self.suffix_combo = QtWidgets.QComboBox()
        self.suffix_combo.setEditable(True)
        self.suffix_combo.setMinimumHeight(34)
        self.suffix_combo.addItems(["_guides"])
        self.suffix_combo.setCurrentText("_guides")
        guide_layout.addWidget(self.suffix_combo)
        main_layout.addLayout(guide_layout)

        # -- Frame Range --
        frame_layout = QtWidgets.QHBoxLayout()
        frame_layout.addWidget(QtWidgets.QLabel("Frame Range:"))
        self.frame_start_spin = QtWidgets.QSpinBox()
        self.frame_start_spin.setRange(-100000, 100000)
        self.frame_end_spin = QtWidgets.QSpinBox()
        self.frame_end_spin.setRange(-100000, 100000)
        # Default from Maya timeline
        self.frame_start_spin.setValue(int(cmds.playbackOptions(q=True, minTime=True)))
        self.frame_end_spin.setValue(int(cmds.playbackOptions(q=True, maxTime=True)))
        frame_layout.addWidget(self.frame_start_spin)
        frame_layout.addWidget(self.frame_end_spin)
        main_layout.addLayout(frame_layout)

        # -- Separator --
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        main_layout.addWidget(separator)

        # -- Buttons --
        btn_layout = QtWidgets.QHBoxLayout()
        single_btn = QtWidgets.QPushButton("Export Single Frame")
        single_btn.clicked.connect(self._export_single_frame)
        btn_layout.addWidget(single_btn)
        anim_btn = QtWidgets.QPushButton("Export Animation")
        anim_btn.clicked.connect(self._export_animation)
        btn_layout.addWidget(anim_btn)
        main_layout.addLayout(btn_layout)

        # -- Status --
        self.status_label = QtWidgets.QLabel("")
        main_layout.addWidget(self.status_label)

    def _browse_export_dir(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Export Directory", self.dir_edit.text()
        )
        if directory:
            self.dir_edit.setText(directory)

    def _get_export_dir(self):
        export_dir = self.dir_edit.text().strip()
        if not export_dir:
            raise ValueError("Export directory is not set.")
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
        return export_dir

    def _set_status(self, message, is_error=False):
        color = "red" if is_error else "green"
        self.status_label.setStyleSheet("color: {}".format(color))
        self.status_label.setText(message)
        print("[XGen Export] {}".format(message))
        QtWidgets.QApplication.processEvents()

    def _export_single_frame(self):
        cmds.waitCursor(state=True)
        cmds.undoInfo(openChunk=True)
        try:
            export_dir = self._get_export_dir()
            suffix = self.suffix_combo.currentText()
            guide_root = self.guide_root_edit.text().strip()

            self._set_status("Getting description mesh map...")

            # 1. Description mesh map + save JSON
            description_mesh_map = get_description_mesh_map()
            dump_map = {}
            for k, v in description_mesh_map.items():
                dump_map[k] = [p.split('|')[-1] for p in v]
            json.dump(
                dump_map,
                open(os.path.join(export_dir, 'description_mesh_map.json'), 'w'),
                indent=4,
            )

            # 2. Export mesh patches
            self._set_status("Exporting patches...")
            mesh_patches = []
            for v in description_mesh_map.values():
                mesh_patches.extend(v)
            mesh_patches = list(set(mesh_patches))
            if mesh_patches:
                export_group(mesh_patches, export_dir, file_name='patches')

            # 3. Export strands
            self._set_status("Exporting strands...")
            spline_descriptions = convert_to_interactive_groom(
                cmds.ls(type='xgmDescription', long=True)
            )
            if spline_descriptions:
                export_interactive_groom(
                    spline_descriptions, export_dir, file_name='strands'
                )
                cmds.delete(spline_descriptions)

            # 4. Export guides
            self._set_status("Exporting guides...")
            guides_group, rollback_map = create_guide_attributes(
                root=guide_root, suffix=suffix
            )
            export_group(guides_group, export_dir, file_name='guides')
            rollback_guide_attributes(
                guides_group, rollback_map, delete_guide_groups=True
            )
            # 5. Merge strands + guides and add groom attributes
            self._set_status("Merging and processing groom abc...")
            strands_abc = os.path.join(export_dir, 'strands.abc')
            guides_abc = os.path.join(export_dir, 'guides.abc')
            groom_abc = os.path.join(export_dir, 'groom.abc')
            patches_abc = os.path.join(export_dir, 'patches.abc')
            mesh_map_json = os.path.join(export_dir, 'description_mesh_map.json')

            merge_and_process_abc(
                strands_abc,
                guides_abc,
                groom_abc,
                patches_abc=patches_abc if os.path.exists(patches_abc) else None,
                mesh_map_json=mesh_map_json if os.path.exists(mesh_map_json) else None,
            )

            self._set_status("Export complete: {}".format(export_dir))

        except Exception as e:
            self._set_status("Error: {}".format(e), is_error=True)
            import traceback
            traceback.print_exc()
        finally:
            cmds.undoInfo(closeChunk=True)
            cmds.waitCursor(state=False)

    @staticmethod
    def _find_guide_grps(guide_root):
        """Find all guide_grp nodes in scene (namespaced and non-namespaced)."""
        guide_grps = cmds.ls('*:' + guide_root, long=True, type='transform') or []
        non_ns = cmds.ls(guide_root, long=True, type='transform') or []
        seen = set(guide_grps)
        for item in non_ns:
            if item not in seen:
                guide_grps.append(item)
                seen.add(item)
        return guide_grps

    @staticmethod
    def _derive_export_name(guide_grp_path):
        """Derive ABC file name from a guide_grp node path.

        For referenced nodes, parses the reference file path:
            .../assets/<asset_types>/<asset_name>/<dept>/file.mb
        Returns: "<asset_types>+<asset_name>+<reference_index>"
        Fallback: namespace or "guides"
        """
        short_name = guide_grp_path.split('|')[-1]
        namespace = short_name.rsplit(':', 1)[0] if ':' in short_name else ''

        if namespace:
            # Use the namespaced node (without long path) for referenceQuery
            ns_node = short_name
            try:
                ref_node = cmds.referenceQuery(ns_node, referenceNode=True)
                ref_path = cmds.referenceQuery(ref_node, filename=True, withoutCopyNumber=True)
                ref_path = ref_path.replace('\\', '/')
            except RuntimeError:
                return namespace

            # Parse: .../assets/<asset_types>/<asset_name>/<dept>/file.mb
            lower_path = ref_path.lower()
            if '/assets/' in lower_path:
                assets_idx = lower_path.index('/assets/')
                after_assets = ref_path[assets_idx + len('/assets/'):]
                parts = after_assets.split('/')
                if len(parts) >= 3:
                    asset_types = parts[0]
                    asset_name = parts[1]
                    # Derive reference_index: strip asset_name from namespace
                    remainder = namespace.replace(asset_name, '', 1)
                    # remainder could be '', '1', '2', etc.
                    try:
                        ref_index = int(remainder) if remainder else 0
                    except ValueError:
                        ref_index = 0
                    return '{}+{}+{}'.format(asset_types, asset_name, ref_index)

            # Fallback for referenced but non-matching path pattern
            return namespace

        return 'guides'

    def _export_animation(self):
        cmds.waitCursor(state=True)
        scene_path = cmds.file(q=True, sceneName=True)
        need_reopen = False
        try:
            export_dir = self._get_export_dir()
            suffix = self.suffix_combo.currentText()
            guide_root = self.guide_root_edit.text().strip()
            frame_start = self.frame_start_spin.value()
            frame_end = self.frame_end_spin.value()

            guide_grps = self._find_guide_grps(guide_root)
            if not guide_grps:
                raise ValueError(
                    "No '{}' nodes found in scene.".format(guide_root)
                )

            # Build export plan while references still exist (referenceQuery
            # needs live reference nodes).
            # Each entry: (short_name, file_name, ref_file_or_None)
            export_plan = []
            for grp_path in guide_grps:
                file_name = self._derive_export_name(grp_path)
                short_name = grp_path.split('|')[-1]
                # Determine which reference file this guide_grp belongs to
                ref_file = None
                try:
                    if cmds.referenceQuery(grp_path, isNodeReferenced=True):
                        ref_node = cmds.referenceQuery(
                            grp_path, referenceNode=True
                        )
                        ref_file = cmds.referenceQuery(
                            ref_node, filename=True, withoutCopyNumber=True
                        )
                except RuntimeError:
                    pass
                export_plan.append((short_name, file_name, ref_file))

            has_references = any(ref for _, _, ref in export_plan)

            if has_references:
                if not scene_path:
                    raise ValueError(
                        "Scene must be saved before exporting referenced guides."
                    )
                self._set_status("Checking for unsaved changes...")
                if not check_save_changes():
                    self._set_status("Export cancelled.")
                    return
                # Refresh scene_path in case it changed after a Save As
                scene_path = cmds.file(q=True, sceneName=True)
                need_reopen = True

            # --- Export non-referenced guide_grps first (no import needed) ---
            local_plan = [
                (sn, fn) for sn, fn, rf in export_plan if rf is None
            ]
            if local_plan:
                all_grps = self._find_guide_grps(guide_root)
                grp_by_short = {}
                for grp_path in all_grps:
                    grp_by_short[grp_path.split('|')[-1]] = grp_path

                for short_name, file_name in local_plan:
                    grp_path = grp_by_short.get(short_name)
                    if not grp_path:
                        print(
                            "[XGen Export] Warning: '{}' not found, skipping."
                            .format(short_name)
                        )
                        continue
                    self._set_status(
                        "Exporting {} ({}-{})...".format(
                            file_name, frame_start, frame_end
                        )
                    )
                    guides_group, rollback_map = create_guide_attributes(
                        root=grp_path, suffix=suffix
                    )
                    export_group(
                        guides_group,
                        export_dir,
                        file_name=file_name,
                        frame_start=frame_start,
                        frame_end=frame_end,
                    )
                    cmds.delete(guides_group)

            # --- Export referenced guide_grps one at a time ---
            ref_plan = [
                (sn, fn, rf) for sn, fn, rf in export_plan if rf is not None
            ]
            for short_name, file_name, ref_file in ref_plan:
                # Import only the reference that contains this guide_grp
                self._set_status(
                    "Importing reference: {}...".format(
                        os.path.basename(ref_file)
                    )
                )
                # Find the live reference node for this file
                ref_imported = False
                for ref in (cmds.file(q=True, reference=True) or []):
                    ref_path = cmds.referenceQuery(
                        ref, filename=True, withoutCopyNumber=True
                    )
                    if os.path.normpath(ref_path) == os.path.normpath(ref_file):
                        cmds.file(ref, importReference=True)
                        ref_imported = True
                        break

                if not ref_imported:
                    print(
                        "[XGen Export] Warning: reference '{}' not found in "
                        "scene, skipping '{}'.".format(ref_file, short_name)
                    )
                    continue

                # Re-find the guide_grp (long path changes after import)
                all_grps = self._find_guide_grps(guide_root)
                grp_by_short = {}
                for grp_path in all_grps:
                    grp_by_short[grp_path.split('|')[-1]] = grp_path

                grp_path = grp_by_short.get(short_name)
                if not grp_path:
                    print(
                        "[XGen Export] Warning: '{}' not found after import, "
                        "skipping.".format(short_name)
                    )
                    continue

                self._set_status(
                    "Exporting {} ({}-{})...".format(
                        file_name, frame_start, frame_end
                    )
                )
                guides_group, rollback_map = create_guide_attributes(
                    root=grp_path, suffix=suffix
                )
                export_group(
                    guides_group,
                    export_dir,
                    file_name=file_name,
                    frame_start=frame_start,
                    frame_end=frame_end,
                )
                cmds.delete(guides_group)

            self._set_status(
                "Animation export complete: {}".format(export_dir)
            )

        except Exception as e:
            self._set_status("Error: {}".format(e), is_error=True)
            import traceback
            traceback.print_exc()
        finally:
            if need_reopen and scene_path:
                self._set_status("Reopening scene...")
                cmds.file(scene_path, open=True, force=True)
            cmds.waitCursor(state=False)


def show():
    # Close any existing instance by object name so only one can exist
    main_window = get_maya_main_window()
    if main_window is not None:
        for widget in main_window.findChildren(
            QtWidgets.QWidget, XGenExportTool.OBJECT_NAME
        ):
            widget.close()
            widget.deleteLater()

    tool = XGenExportTool(parent=main_window)
    tool.show()
    return tool
