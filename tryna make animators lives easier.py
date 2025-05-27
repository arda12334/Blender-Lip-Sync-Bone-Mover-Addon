import bpy
import os
import subprocess
import json

from bpy.props import (
    StringProperty, CollectionProperty, PointerProperty,
    IntProperty, FloatVectorProperty, BoolProperty
)
from bpy.types import Panel, Operator, PropertyGroup, UIList
from bpy_extras.io_utils import ExportHelper, ImportHelper

bl_info = {
    "name": "Lipsyncer",
    "author": "ChatGPT & tahavr",
    "version": (1, 1, 0),
    "blender": (4, 3, 0),        # change this to match your Blender version
    "location": "View3D > Sidebar > Lip Sync",
    "description": "Viseme lipsync using Rhubarb (manual setup)",
    "category": "Animation",
}

# — Utilities —
def parse_rhubarb_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    if "mouthCues" in d:
        return d["mouthCues"]
    raise ValueError("Invalid Rhubarb JSON format")

# — Data Models —
class VisemeItem(PropertyGroup):
    name: StringProperty(name="Viseme", default="A")
    position: FloatVectorProperty(
        name="Bone Location",
        subtype='TRANSLATION',
        size=3, default=(0.0,0.0,0.0),
        precision=4
    )
    preview: BoolProperty(
        name="Preview", default=False,
        description="Preview this viseme on the bone",
        update=lambda self,ctx: self.update_preview(ctx)
    )
    def update_preview(self, context):
        if not self.preview: return
        props = context.scene.lipsync_props
        for v in props.visemes:
            if v is not self:
                v.preview = False
        bone = context.object.pose.bones.get(props.target_bone)
        if bone:
            bone.location = self.position

class LipsyncProperties(PropertyGroup):
    audio_file: StringProperty(
        name="Audio File", subtype='FILE_PATH',
        description=".wav or .mp3"
    )
    ffmpeg_exe: StringProperty(
        name="FFmpeg EXE", subtype='FILE_PATH',
        description="Path to ffmpeg.exe for audio conversion"
    )
    rhubarb_exe: StringProperty(
        name="Rhubarb EXE", subtype='FILE_PATH',
        description="Path to rhubarb.exe"
    )
    rhubarb_txt: StringProperty(
        name="Rhubarb TXT", subtype='FILE_PATH',
        description="Rhubarb output (JSON saved as .txt)"
    )
    target_bone: StringProperty(
        name="Target Bone", default="mouth_ctrl",
        description="Bone to animate"
    )
    visemes: CollectionProperty(type=VisemeItem)
    active_viseme_index: IntProperty()
    frame_step: IntProperty(
        name="Frame Step", default=1,
        description="Insert a keyframe every N frames"
    )
    blend_frames: IntProperty(
        name="Blend Frames", default=1,
        description="Cross-fade over first N frames of each viseme"
    )

# — Preset Export/Import —
class OT_ExportVisemePreset(Operator, ExportHelper):
    bl_idname = "lipsync.export_preset"
    bl_label = "Export Viseme Preset"
    bl_description = "Save current viseme names & positions to JSON"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    def execute(self, context):
        p = context.scene.lipsync_props
        data = [{"name":v.name,"position":list(v.position)} for v in p.visemes]
        try:
            with open(self.filepath,'w',encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.report({'INFO'},f"Preset saved → {self.filepath}")
        except Exception as e:
            self.report({'ERROR'},f"Export failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class OT_ImportVisemePreset(Operator, ImportHelper):
    bl_idname = "lipsync.import_preset"
    bl_label = "Import Viseme Preset"
    bl_description = "Load viseme names & positions from JSON"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    def execute(self, context):
        p = context.scene.lipsync_props
        try:
            with open(self.filepath,'r',encoding='utf-8') as f:
                data = json.load(f)
            p.visemes.clear()
            for e in data:
                v = p.visemes.add()
                v.name = e.get("name","")
                v.position = e.get("position",[0,0,0])
            self.report({'INFO'},f"Preset loaded ← {self.filepath}")
        except Exception as e:
            self.report({'ERROR'},f"Import failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

# — Core Operators —
class OT_RunRhubarb(Operator):
    bl_idname = "lipsync.run_rhubarb"
    bl_label = "Run Rhubarb"
    bl_description = "Convert audio→WAV & run Rhubarb"
    bl_options = {'REGISTER'}
    def execute(self, context):
        p = context.scene.lipsync_props
        audio_in = bpy.path.abspath(p.audio_file)
        # if not WAV, convert
        if not audio_in.lower().endswith(".wav"):
            out_wav = os.path.splitext(audio_in)[0] + "_conv.wav"
            subprocess.run([
                bpy.path.abspath(p.ffmpeg_exe),
                "-y","-i",audio_in,out_wav
            ], check=True)
            audio = out_wav
        else:
            audio = audio_in
        out_txt = os.path.splitext(audio)[0] + "_rhubarb.txt"
        subprocess.run([
            bpy.path.abspath(p.rhubarb_exe),
            "-f","json",audio,"-o",out_txt
        ], check=True)
        p.rhubarb_txt = out_txt
        self.report({'INFO'},f"Output → {out_txt}")
        return {'FINISHED'}

class OT_ImportVisemes(Operator):
    bl_idname = "lipsync.import_visemes"
    bl_label = "Import Visemes"
    bl_description = "Load viseme cues from Rhubarb output"
    bl_options = {'REGISTER'}
    def execute(self, context):
        p = context.scene.lipsync_props
        cues = parse_rhubarb_json(bpy.path.abspath(p.rhubarb_txt))
        names = sorted({c["value"] for c in cues})
        existing = {v.name for v in p.visemes}
        for n in names:
            if n not in existing:
                v = p.visemes.add()
                v.name = n
        self.report({'INFO'},f"Imported {len(names)} visemes")
        return {'FINISHED'}

class OT_AddViseme(Operator):
    bl_idname = "lipsync.add_viseme"
    bl_label = "Add Viseme"
    bl_description = "Append an empty viseme entry"
    def execute(self, context):
        p = context.scene.lipsync_props
        v = p.visemes.add()
        v.name = f"V{len(p.visemes)}"
        p.active_viseme_index = len(p.visemes)-1
        return {'FINISHED'}

class OT_RemoveViseme(Operator):
    bl_idname = "lipsync.remove_viseme"
    bl_label = "Remove Viseme"
    bl_description = "Delete the selected viseme"
    def execute(self, context):
        p = context.scene.lipsync_props
        idx = p.active_viseme_index
        if idx >= 0:
            p.visemes.remove(idx)
        return {'FINISHED'}

class OT_GenerateLipsync(Operator):
    bl_idname = "lipsync.generate_keys"
    bl_label = "Generate Lipsync"
    bl_description = "Keyframe bone for each viseme cue"
    bl_options = {'REGISTER','UNDO'}
    def execute(self, context):
        p = context.scene.lipsync_props
        obj = context.object
        bone = obj.pose.bones.get(p.target_bone)
        cues = parse_rhubarb_json(bpy.path.abspath(p.rhubarb_txt))
        fps = context.scene.render.fps / context.scene.render.fps_base
        prev = None; cnt = 0
        for c in cues:
            nm = c["value"]
            m = next((v for v in p.visemes if v.name==nm), None)
            if not m: continue
            st = int(c["start"]*fps)
            ed = int(c.get("end",c["start"]+0.1)*fps)
            for f in range(st, ed+1, p.frame_step):
                if prev and p.blend_frames>0 and f < st + p.blend_frames:
                    t = (f - st)/p.blend_frames
                    loc = (
                        prev[0]*(1-t) + m.position[0]*t,
                        prev[1]*(1-t) + m.position[1]*t,
                        prev[2]*(1-t) + m.position[2]*t,
                    )
                else:
                    loc = m.position
                bone.location = loc
                bone.keyframe_insert("location", frame=f)
                cnt += 1
            prev = m.position
        self.report({'INFO'},f"Inserted {cnt} keyframes")
        return {'FINISHED'}

# — UI List & Panel —
class VISEME_UL_List(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "preview", text="", icon='HIDE_OFF' if item.preview else 'HIDE_ON')
        row.prop(item, "name", text="", emboss=False)
        row.prop(item, "position", text="")

class VIEW3D_PT_LipsyncPanel(Panel):
    bl_label = "Lipsyncer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lip Sync"

    def draw(self, context):
        layout = self.layout
        p = context.scene.lipsync_props

        # Preset buttons
        row = layout.row(align=True)
        row.operator("lipsync.import_preset", icon='IMPORT', text="Import Preset")
        row.operator("lipsync.export_preset", icon='EXPORT', text="Export Preset")
        layout.separator()

        # File paths
        layout.prop(p, "audio_file", text="Audio")
        layout.prop(p, "ffmpeg_exe", text="FFmpeg.exe")
        layout.prop(p, "rhubarb_exe", text="Rhubarb.exe")
        layout.operator("lipsync.run_rhubarb", icon='PLAY')

        layout.prop(p, "rhubarb_txt", text="Output TXT")
        layout.operator("lipsync.import_visemes", icon='IMPORT')

        layout.prop_search(p, "target_bone", context.object.data, "bones", text="Bone")

        box = layout.box()
        box.label(text="Timing:")
        box.prop(p, "frame_step")
        box.prop(p, "blend_frames")

        row = layout.row()
        row.template_list("VISEME_UL_List", "", p, "visemes", p, "active_viseme_index", rows=6)
        col = row.column(align=True)
        col.operator("lipsync.add_viseme", icon='ADD')
        col.operator("lipsync.remove_viseme", icon='REMOVE')

        layout.operator("lipsync.generate_keys", icon='ARMATURE_DATA')

# — Registration —
classes = (
    VisemeItem,
    LipsyncProperties,
    OT_ExportVisemePreset,
    OT_ImportVisemePreset,
    OT_RunRhubarb,
    OT_ImportVisemes,
    OT_AddViseme,
    OT_RemoveViseme,
    OT_GenerateLipsync,
    VISEME_UL_List,
    VIEW3D_PT_LipsyncPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lipsync_props = PointerProperty(type=LipsyncProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.lipsync_props

if __name__=="__main__":
    register()
