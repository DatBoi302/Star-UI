import os
import json
import re
import dearpygui.dearpygui as dpg
from tkinter import filedialog, Tk
import colorsys
import copy
import math
import ctypes
import zipfile
import shutil
import io
import threading
import time
import hashlib
import atexit
import queue
import multiprocessing as mp
from multiprocessing import shared_memory

# --- Library Import Verify ---
try:
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    HAS_IMG_LIBS = True
except ImportError:
    HAS_IMG_LIBS = False
    print("WARNING: NumPy and Pillow not found. Texture Lab will be disabled.")

# --- Defaults & Directories ---
STAR_UI_DIR = "Star_UI"
DATA_DIR = os.path.join(STAR_UI_DIR, "Data")
LAYERS_DIR = os.path.join(STAR_UI_DIR, "Layers")
PRESETS_ROOT = os.path.join(STAR_UI_DIR, "Presets")
CONFIG_PRESETS_DIR = os.path.join(PRESETS_ROOT, "Settings")
HUD_PRESETS_DIR = os.path.join(PRESETS_ROOT, "Textures")
FACTION_PRESETS_DIR = os.path.join(PRESETS_ROOT, "Factions") 
FLAGS_DIR = os.path.join(STAR_UI_DIR, "Flags")
BGS_DIR = os.path.join(STAR_UI_DIR, "Backgrounds")
CACHE_DIR = os.path.join(STAR_UI_DIR, ".cache")

TOOL_CONFIG = os.path.join(STAR_UI_DIR, "Star_UI_Settings.json") 
DEFAULTS_FILE = os.path.join(STAR_UI_DIR, "Color_Defaults.json")
DESCRIPTIONS_FILE = os.path.join(STAR_UI_DIR, "Color_Descriptions.json")
THEMES_FILE = os.path.join(STAR_UI_DIR, "Application_Themes.json")
RECOMMENDED_IMPORT_FILE = os.path.join(STAR_UI_DIR, "Recommended_Import.json")
FACTION_DEFAULTS_FILE = os.path.join(STAR_UI_DIR, "Color_Faction_Defaults.json")
ICON_FILENAME = os.path.join(STAR_UI_DIR, "Star_UI_Icon.ico")
LAYERS_JSON_FILE = os.path.join(STAR_UI_DIR, "ui_Layers.json")
SETUP_IMPORT_JSON = os.path.join(STAR_UI_DIR, "Setup_Import.json")

# --- GL Sampler Fix & Custom UV Mapper ---
def process_texture_for_opengl(img_pil):
    if not HAS_IMG_LIBS:
        return img_pil, img_pil.size[0], img_pil.size[1], img_pil.size[0], img_pil.size[1], (0.0, 0.0), (1.0, 1.0)
        
    orig_w, orig_h = img_pil.size
    if orig_w == 0 or orig_h == 0:
        return img_pil, orig_w, orig_h, orig_w, orig_h, (0.0, 0.0), (1.0, 1.0)

    arr = np.array(img_pil)
    if arr.shape[2] == 4:
        rgb = arr[:, :, :3]
        alpha = arr[:, :, 3]
        color_mask = alpha > 0
        
        if not color_mask.all() and color_mask.any():
            max_dim = max(arr.shape[0], arr.shape[1])
            step = 1
            while step < max_dim:
                target_void = ~color_mask
                if not target_void.any(): break
                out_rgb = rgb.copy()
                out_mask = color_mask.copy()
                shifts = [(-step, 0), (step, 0), (0, -step), (0, step), 
                          (-step, -step), (-step, step), (step, -step), (step, step)]
                for dy, dx in shifts:
                    sy1, sy2 = max(0, -dy), arr.shape[0] - max(0, dy)
                    sx1, sx2 = max(0, -dx), arr.shape[1] - max(0, dx)
                    dy1, dy2 = max(0, dy), arr.shape[0] - max(0, -dy)
                    dx1, dx2 = max(0, dx), arr.shape[1] - max(0, -dx)
                    update = target_void[dy1:dy2, dx1:dx2] & color_mask[sy1:sy2, sx1:sx2]
                    out_rgb[dy1:dy2, dx1:dx2][update] = rgb[sy1:sy2, sx1:sx2][update]
                    out_mask[dy1:dy2, dx1:dx2][update] = True
                    target_void[dy1:dy2, dx1:dx2][update] = False
                rgb = out_rgb
                color_mask = out_mask
                step *= 2
        arr[:, :, :3] = rgb

    padded_arr = np.pad(arr, ((1, 1), (1, 1), (0, 0)), mode='edge') if arr.ndim == 3 else np.pad(arr, ((1, 1), (1, 1)), mode='edge')
    padded_img = Image.fromarray(padded_arr)
    
    pad_w, pad_h = padded_img.size
    
    uv_min = (1.0 / pad_w, 1.0 / pad_h)
    uv_max = ((orig_w + 1) / pad_w, (orig_h + 1) / pad_h)
    
    return padded_img, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max

# --- SHM & IPC POP-OUT MANAGER ---
class SHMManager:
    def __init__(self):
        self.blocks = {}
        self.name_map = {}

    def write(self, name, np_array):
        base_name = name.replace("/", "_").replace("\\", "_").replace(".", "_")
        size = np_array.nbytes
        
        safe_name = self.name_map.get(base_name, base_name)
        
        if safe_name in self.blocks:
            if self.blocks[safe_name].size != size:
                self.blocks[safe_name].close()
                try: self.blocks[safe_name].unlink()
                except: pass
                del self.blocks[safe_name]
                # Bypass Windows zombie locking by mutating the name
                safe_name = f"{base_name}_{int(time.time()*1000)}"
                self.name_map[base_name] = safe_name
        
        if safe_name not in self.blocks:
            try:
                self.blocks[safe_name] = shared_memory.SharedMemory(name=safe_name, create=True, size=size)
            except FileExistsError:
                try:
                    shm = shared_memory.SharedMemory(name=safe_name)
                    shm.unlink()
                except Exception: pass
                # Try one more time with a forced unique name
                safe_name = f"{base_name}_{int(time.time()*10000)}"
                self.name_map[base_name] = safe_name
                self.blocks[safe_name] = shared_memory.SharedMemory(name=safe_name, create=True, size=size)
        
        target = np.ndarray(np_array.shape, dtype=np_array.dtype, buffer=self.blocks[safe_name].buf)
        target[:] = np_array[:]
        return safe_name

    def cleanup(self):
        for name, shm in self.blocks.items():
            try:
                shm.close()
                shm.unlink()
            except: pass
        self.blocks.clear()

# --- TOP-LEVEL IPC POP-OUT LOOP ---
def popout_process_loop(cmd_queue, theme_data):
    dpg.create_context()
    
    with dpg.theme() as p_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, theme_data.get("WindowBg", [15,15,20,255]))
    dpg.bind_theme(p_theme)

    with dpg.texture_registry(tag="pop_tex_reg"):
        dpg.add_static_texture(width=1, height=1, default_value=[0,0,0,0], tag="static_void_texture")
    
    user32 = ctypes.windll.user32
    w, h = 1280, 760
    x = int((user32.GetSystemMetrics(0) - w) / 2) + 50
    y = int((user32.GetSystemMetrics(1) - h) / 2) + 50
    
    dpg.create_viewport(title="Star UI - Remote Live Preview", width=w, height=h, x_pos=x, y_pos=y, decorated=True)

    with dpg.window(tag="pop_main_win"):
        dpg.add_drawlist(tag="pop_drawlist", width=1920, height=1080)
    dpg.set_primary_window("pop_main_win", True)

    state = {
        "zoom": 1.0,
        "bg": "",
        "layers": {},
        "colors": {},
        "active_tex_tags": {}
    }
    shm_registry = {}

    def handle_redraw():
        if not dpg.does_item_exist("pop_drawlist"): return
        dpg.delete_item("pop_drawlist", children_only=True)
        
        scale = state["zoom"]
        cv_w, cv_h = int(1920 * scale), int(1080 * scale)
        dpg.configure_item("pop_drawlist", width=cv_w, height=cv_h)

        bg_name = state["bg"]
        if bg_name:
            bg_tag = f"pop_bg_{bg_name}"
            if not dpg.does_alias_exist(bg_tag):
                bg_path = os.path.join("Star_UI", "Backgrounds", bg_name)
                if os.path.exists(bg_path):
                    try:
                        bw, bh, bc, bd = dpg.load_image(bg_path)
                        dpg.add_static_texture(width=bw, height=bh, default_value=bd, tag=bg_tag, parent="pop_tex_reg")
                    except: pass
            if dpg.does_alias_exist(bg_tag):
                dpg.draw_image(bg_tag, pmin=(0,0), pmax=(cv_w, cv_h), parent="pop_drawlist")
            else: dpg.draw_rectangle((0,0), (cv_w, cv_h), fill=(10,10,12,255), thickness=0, parent="pop_drawlist")
        else:
            dpg.draw_rectangle((0,0), (cv_w, cv_h), fill=(10,10,12,255), thickness=0, parent="pop_drawlist")

        sorted_keys = sorted(state["layers"].keys())
        for key in sorted_keys:
            layer = state["layers"][key]
            if layer.get("disabled", False): continue
            
            ax, ay = layer["anchor_x"], layer["anchor_y"]
            w, h = layer["mask_width"], layer["mask_height"]
            origin = layer.get("anchor_origin", "top_left")
            stretch = layer.get("stretch_to_mask", False)
            color_key = layer.get("color_key", "")
            tint_color = state["colors"].get(color_key, [255, 255, 255, 255]) if color_key else [255, 255, 255, 255]

            tex_id = layer.get("mask_file", "") if layer.get("is_color_mask", False) else layer.get("texture_file", "")
            tex_tag = state.get("active_tex_tags", {}).get(tex_id, f"pop_tex_{tex_id}")
            if not dpg.does_alias_exist(tex_tag): continue

            meta = dpg.get_item_user_data(tex_tag)
            if not meta: continue
            actual_w, actual_h = meta["w"], meta["h"]
            uv_min, uv_max = meta["uv_min"], meta["uv_max"]

            if layer.get("is_repeating", False) or stretch: box_w, box_h = w, h
            elif layer.get("is_color_mask", False): box_w, box_h = 1920, 1080 
            else: box_w, box_h = actual_w, actual_h 

            if origin == "bottom_right": tx, ty = ax - box_w, ay - box_h
            elif origin == "bottom_left": tx, ty = ax, ay - box_h
            elif origin == "top_right": tx, ty = ax - box_w, ay
            elif origin == "center": tx, ty = ax - (box_w/2.0), ay - (box_h/2.0)
            else: tx, ty = ax, ay

            if layer.get("is_color_mask", False):
                p1, p2 = (0, 0), (1920 * scale, 1080 * scale)
                dpg.draw_image(tex_tag, pmin=p1, pmax=p2, uv_min=uv_min, uv_max=uv_max, color=tint_color, parent="pop_drawlist")
            elif layer.get("is_repeating", False):
                vw, vh = actual_w, actual_h 
                if vw == 0 or vh == 0: continue
                curr_y = ty
                max_y = ty + box_h
                while curr_y < max_y:
                    curr_x = tx
                    max_x = tx + box_w
                    while curr_x < max_x:
                        draw_w, draw_h = min(vw, max_x - curr_x), min(vh, max_y - curr_y)
                        uv_max_u, uv_max_v = draw_w / vw, draw_h / vh
                        mapped_u_max = uv_min[0] + (uv_max_u * (uv_max[0] - uv_min[0]))
                        mapped_v_max = uv_min[1] + (uv_max_v * (uv_max[1] - uv_min[1]))
                        p1 = (curr_x * scale, curr_y * scale)
                        p2 = ((curr_x + draw_w) * scale, (curr_y + draw_h) * scale)
                        dpg.draw_image(tex_tag, pmin=p1, pmax=p2, uv_min=uv_min, uv_max=(mapped_u_max, mapped_v_max), color=tint_color, parent="pop_drawlist")
                        curr_x += vw
                    curr_y += vh
            else:
                p1 = (tx * scale, ty * scale)
                p2 = ((tx + box_w) * scale, (ty + box_h) * scale)
                dpg.draw_image(tex_tag, pmin=p1, pmax=p2, uv_min=uv_min, uv_max=uv_max, color=tint_color, parent="pop_drawlist")

    dpg.setup_dearpygui()
    dpg.show_viewport()
    
    try:
        while dpg.is_dearpygui_running():
            needs_redraw = False
            latest_state = None
            
            while not cmd_queue.empty():
                try:
                    cmd = cmd_queue.get_nowait()
                    if cmd["type"] == "exit":
                        dpg.stop_dearpygui()
                        break
                    elif cmd["type"] == "state":
                        latest_state = cmd
                    elif cmd["type"] == "tex_shm":
                        shm_name = cmd["shm_name"]
                        t_id = cmd["id"]
                        tag = f"pop_tex_{shm_name}"
                        try:
                            if shm_name not in shm_registry:
                                shm_registry[shm_name] = shared_memory.SharedMemory(name=shm_name)
                            shm = shm_registry[shm_name]
                            
                            raw_data = np.ndarray((cmd["size"],), dtype=np.uint8, buffer=shm.buf)
                            dpg_data = (raw_data.astype(np.float32) / 255.0)
                            
                            if not dpg.does_alias_exist(tag):
                                dpg.add_dynamic_texture(width=cmd["pad_w"], height=cmd["pad_h"], default_value=dpg_data, tag=tag, parent="pop_tex_reg")
                            else:
                                dpg.set_value(tag, dpg_data)
                                
                            state["active_tex_tags"][t_id] = tag
                            
                            dpg.set_item_user_data(tag, {
                                "w": cmd["orig_w"], "h": cmd["orig_h"],
                                "uv_min": cmd["uv_min"], "uv_max": cmd["uv_max"]
                            })
                            needs_redraw = True
                        except Exception as e:
                            print(f"[Remote] SHM Read Error for {t_id}: {e}")
                except queue.Empty:
                    break

            if latest_state:
                state["zoom"] = latest_state.get("zoom", state["zoom"])
                state["bg"] = latest_state.get("bg", state["bg"])
                state["layers"] = latest_state.get("layers", state["layers"])
                state["colors"] = latest_state.get("colors", state["colors"])
                needs_redraw = True

            if needs_redraw:
                handle_redraw()
            
            dpg.render_dearpygui_frame()
    finally:
        for shm in shm_registry.values():
            try: shm.close()
            except: pass
        dpg.destroy_context()

# --- STYLE-EDITOR CONFIG ---
DEFAULT_STYLES = {
    "WindowPadding": [9, 6], 
    "WindowRounding": 8, 
    "WindowBorderSize": 1, 
    "WindowMinSize": [32, 32], 
    "WindowTitleAlign": [0.5, 0.5], 
    "ChildRounding": 5, 
    "ChildBorderSize": 1, 
    "PopupRounding": 5, 
    "PopupBorderSize": 1, 
    "FramePadding": [6, 4], 
    "FrameRounding": 5, 
    "FrameBorderSize": 1, 
    "ItemSpacing": [4, 4], 
    "ItemInnerSpacing": [8, 4], 
    "CellPadding": [4, 4], 
    "IndentSpacing": 21, 
    "ScrollbarSize": 16, 
    "ScrollbarRounding": 3, 
    "GrabMinSize": 14, 
    "GrabRounding": 2, 
    "TabRounding": 2, 
    "ButtonTextAlign": [0.5, 0.5], 
    "SelectableTextAlign": [0.0, 0.0], 
    "TabBarBorderSize": 1, 
}

THEME_COLOR_MAP = {
    "WindowBg": dpg.mvThemeCol_WindowBg,
    "ChildBg": dpg.mvThemeCol_ChildBg,
    "Border": dpg.mvThemeCol_Border,
    "Button": dpg.mvThemeCol_Button,
    "ButtonHover": dpg.mvThemeCol_ButtonHovered,
    "ButtonActive": dpg.mvThemeCol_ButtonActive,
    "Header": dpg.mvThemeCol_Header,
    "TitleBg": dpg.mvThemeCol_TitleBg,
    "TitleBgActive": dpg.mvThemeCol_TitleBgActive,
    "TitleBgCollapsed": dpg.mvThemeCol_TitleBgCollapsed,
    "Text": dpg.mvThemeCol_Text,
    "TextSelected": dpg.mvThemeCol_TextSelectedBg,
    "CheckMark": dpg.mvThemeCol_CheckMark,
    "FrameBg": dpg.mvThemeCol_FrameBg,
    "FrameBgHovered": dpg.mvThemeCol_FrameBgHovered,
    "FrameBgActive": dpg.mvThemeCol_FrameBgActive,
}

THEME_STYLE_MAP = {
    "WindowPadding": dpg.mvStyleVar_WindowPadding,
    "WindowRounding": dpg.mvStyleVar_WindowRounding,
    "WindowBorderSize": dpg.mvStyleVar_WindowBorderSize,
    "WindowMinSize": dpg.mvStyleVar_WindowMinSize,
    "WindowTitleAlign": dpg.mvStyleVar_WindowTitleAlign,
    "ChildRounding": dpg.mvStyleVar_ChildRounding,
    "ChildBorderSize": dpg.mvStyleVar_ChildBorderSize,
    "PopupRounding": dpg.mvStyleVar_PopupRounding,
    "PopupBorderSize": dpg.mvStyleVar_PopupBorderSize,
    "FramePadding": dpg.mvStyleVar_FramePadding,
    "FrameRounding": dpg.mvStyleVar_FrameRounding,
    "FrameBorderSize": dpg.mvStyleVar_FrameBorderSize,
    "ItemSpacing": dpg.mvStyleVar_ItemSpacing,
    "ItemInnerSpacing": dpg.mvStyleVar_ItemInnerSpacing,
    "CellPadding": dpg.mvStyleVar_CellPadding,
    "ScrollbarSize": dpg.mvStyleVar_ScrollbarSize,
    "ScrollbarRounding": dpg.mvStyleVar_ScrollbarRounding,
    "GrabMinSize": dpg.mvStyleVar_GrabMinSize,
    "GrabRounding": dpg.mvStyleVar_GrabRounding,
    "TabRounding": dpg.mvStyleVar_TabRounding,
    "ButtonTextAlign": dpg.mvStyleVar_ButtonTextAlign,
    "SelectableTextAlign": dpg.mvStyleVar_SelectableTextAlign,
    "IndentSpacing": dpg.mvStyleVar_IndentSpacing,
    "TabBarBorderSize": dpg.mvStyleVar_TabBarBorderSize
}

class StarUI:
    def __init__(self):
        self.DEV_SKIP_SETUP = False

        for p in [STAR_UI_DIR, DATA_DIR, LAYERS_DIR, CONFIG_PRESETS_DIR, HUD_PRESETS_DIR, FACTION_PRESETS_DIR, FLAGS_DIR, BGS_DIR, CACHE_DIR]:
            os.makedirs(p, exist_ok=True)

        self.ensure_defaults_exist()
        self.color_descriptions = self.load_json_data(DESCRIPTIONS_FILE, {})
        self.default_colors = self.load_json_data(DEFAULTS_FILE, {})
        self.faction_info = self.load_json_data(FACTION_DEFAULTS_FILE, {})
        self.themes = self.load_json_data(THEMES_FILE, {})
        if not self.themes:
            self.themes = {"Default Dark": {"WindowBg": [15, 15, 20]}}
            
        self.texture_settings = {} 
        self.active_roots = {}     
        self.preview_tags = {} 
        self.snapshot_colors = {}       
        self.state = self.load_tool_state()       
        
        self.base_image_cache = {} 
        self.padded_base_cache = {} 
        
        self.tex_w, self.tex_h = 0, 0
        self.tex_pad_w, self.tex_pad_h = 0, 0
        self.import_tex_w, self.import_tex_h = 1, 1       
        self.import_tex_pad_w, self.import_tex_pad_h = 1, 1
        
        self.loaded_flags = {}
        self.virtual_file_map = {}
        self.available_roots = []
        self.current_virtual_path = None
        self.current_viewing_root = None 
        self.live_preview_custom_tex = {}     
        self.import_staging = {}
        self.quick_copy_slots = [None] * 5        
        self.active_anchor_window = None
        self.active_anchor_button = None        
        self.all_color_keys = [] 
        for cat in self.default_colors:
            for key in self.default_colors[cat]:
                self.all_color_keys.append(key)
        self.all_color_keys.sort()       
        self.hwnd = None
        self.selected_file_theme = None
        self.setup_game_dir = ""
        self.setup_mod_dir = ""
        self.needs_setup = not os.path.exists(TOOL_CONFIG)

        self.shm_manager = SHMManager()
        self.popout_queue = mp.Queue()
        self.popout_process = None
        atexit.register(self.cleanup)

        self._initialize_snapshot()
        self.setup_gui()

    def cleanup(self):
        if self.popout_process and self.popout_process.is_alive():
            self.popout_queue.put({"type": "exit"})
            self.popout_process.join(timeout=2)
            if self.popout_process.is_alive():
                self.popout_process.terminate()
        self.shm_manager.cleanup()

    def save_json_pretty(self, filepath, data):
        try:
            json_str = json.dumps(data, indent=4)
            def collapse(match):
                content = match.group(1)
                if re.match(r'^[\d\s,\.-]+$', content):
                    compressed = re.sub(r'\s+', ' ', content).strip()
                    compressed = re.sub(r',\s*', ', ', compressed) 
                    return f"[{compressed}]"
                return match.group(0)
            json_str = re.sub(r'\[\s*([\d,\s\.-]+?)\s*\]', collapse, json_str, flags=re.DOTALL)
            with open(filepath, 'w') as f:
                f.write(json_str)
        except Exception as e:
            print(f"Error saving JSON to {filepath}: {e}")
            self._set_status(f"Save Error: {e}", [255, 0, 0])

    def ensure_defaults_exist(self): pass

    def load_json_data(self, filename, fallback):
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    return json.load(f)
            except: pass
        return fallback

    def load_tool_state(self):
        init_faction_colors = {}
        init_active_keys = {}
        
        for fname, data in self.faction_info.items():
            init_faction_colors[fname] = copy.deepcopy(data["colors"])
            init_active_keys[fname] = copy.deepcopy(data["active"])

        state = {
            "mod_path": "", 
            "current_colors": copy.deepcopy(self.default_colors),
            "current_faction_colors": init_faction_colors, 
            "active_faction_keys": init_active_keys,
            "app_theme": "Starsector (Default)",
            "show_borders": True,
            "preferred_root": "graphics", 
            "rec_color": [0, 255, 0, 255],
            "global_adjustments": {"h": 0.0, "s": 0.0, "v": 0.0},
            "texture_global_adjustments": {"h": 0.0, "s": 0.0, "v": 0.0},
            "enable_scroll_zoom": True,
            "live_preview_bg": ""
        }
        
        if os.path.exists(TOOL_CONFIG):
            try:
                with open(TOOL_CONFIG, 'r') as f:
                    data = json.load(f)
                for k, v in data.items():
                    if k in state:
                        state[k] = v

                if "rec_color" in state:
                    state["rec_color"] = [max(0, min(255, int(x))) for x in state["rec_color"]]

                for fname, fdata in self.faction_info.items():
                    if fname not in state["current_faction_colors"]:
                        state["current_faction_colors"][fname] = copy.deepcopy(fdata["colors"])
                        state["active_faction_keys"][fname] = copy.deepcopy(fdata["active"])

                if "current_colors" in data:
                    for category, items in self.default_colors.items():
                        if category in data["current_colors"] and isinstance(data["current_colors"][category], dict):
                            for key in items:
                                if key in data["current_colors"][category]:
                                    val = data["current_colors"][category][key]
                                    if isinstance(val, list) and len(val) == 4:
                                        state["current_colors"][category][key] = [max(0, min(255, int(x))) for x in val]
                
                if "texture_settings" in data: self.texture_settings = data["texture_settings"]
                if "active_roots" in data: self.active_roots = data["active_roots"]

            except Exception as e: print(f"Error loading config: {e}")
        return state

    def save_tool_state(self):
        if getattr(self, 'needs_setup', False) and not getattr(self, 'DEV_SKIP_SETUP', False): return
        
        self._pending_save = True
        
        if hasattr(self, '_save_watchdog_thread') and self._save_watchdog_thread.is_alive():
            return
            
        def _save_watchdog():
            while getattr(self, '_pending_save', False):
                self._pending_save = False
                time.sleep(0.3)
                if not getattr(self, '_pending_save', False):
                    try:
                        save_data = copy.deepcopy(self.state)
                        save_data["texture_settings"] = copy.deepcopy(self.texture_settings)
                        save_data["active_roots"] = copy.deepcopy(self.active_roots)
                        self.save_json_pretty(TOOL_CONFIG, save_data)
                    except: pass
                    break

        self._save_watchdog_thread = threading.Thread(target=_save_watchdog, daemon=True)
        self._save_watchdog_thread.start()

    def get_cached_layers(self):
        if not os.path.exists(LAYERS_JSON_FILE): return {}
        mtime = os.path.getmtime(LAYERS_JSON_FILE)
        if getattr(self, '_layers_mtime', 0) != mtime:
            try:
                with open(LAYERS_JSON_FILE, 'r') as f: self._layers_cache = json.load(f)
                self._layers_mtime = mtime
            except: self._layers_cache = {}
        return getattr(self, '_layers_cache', {})

    def _initialize_snapshot(self):
        vals = self.state.get("global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})
        h_shift, s_shift, v_shift = vals["h"], vals["s"], vals["v"]
        self.snapshot_colors = copy.deepcopy(self.state["current_colors"])
        if h_shift != 0 or s_shift != 0 or v_shift != 0:
            for cat, items in self.snapshot_colors.items():
                for sk, rgba in items.items():
                    r, g, b = rgba[0]/255.0, rgba[1]/255.0, rgba[2]/255.0
                    h, s, v = colorsys.rgb_to_hsv(r, g, b)
                    h = (h - h_shift) % 1.0
                    s = max(0.0, min(1.0, s - s_shift))
                    v = max(0.0, min(1.0, v - v_shift))
                    nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
                    self.snapshot_colors[cat][sk] = [int(nr*255), int(ng*255), int(nb*255), rgba[3]]

    def _get_cache_hash(self, file_path, settings):
        if not os.path.exists(file_path): return None
        mtime = os.path.getmtime(file_path)
        s_str = json.dumps(settings, sort_keys=True)
        raw = f"{file_path}_{mtime}_{s_str}".encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def _check_cache(self, file_path, settings):
        chash = self._get_cache_hash(file_path, settings)
        if not chash: return None
        cache_file = os.path.join(CACHE_DIR, f"{chash}.npz")
        if os.path.exists(cache_file):
            try:
                loaded = np.load(cache_file)
                meta = loaded['meta']
                uint8_data = loaded['data']
                return uint8_data, meta[0], meta[1], meta[2], meta[3], (meta[4], meta[5]), (meta[6], meta[7])
            except Exception as e: pass
        return None

    def _save_cache(self, file_path, settings, final_data, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max):
        chash = self._get_cache_hash(file_path, settings)
        if not chash: return
        cache_file = os.path.join(CACHE_DIR, f"{chash}.npz")
        
        if hasattr(self, '_cache_timer') and self._cache_timer.is_alive():
            self._cache_timer.cancel()
            
        def do_save():
            try:
                meta = np.array([orig_w, orig_h, pad_w, pad_h, uv_min[0], uv_min[1], uv_max[0], uv_max[1]], dtype=np.float32)
                np.savez_compressed(cache_file, data=final_data, meta=meta)
            except: pass
            
        self._cache_timer = threading.Timer(0.3, do_save)
        self._cache_timer.start()

    def _get_static_texture_cached(self, file_path):
        if not os.path.exists(file_path) or not HAS_IMG_LIBS: return None
        mtime = os.path.getmtime(file_path)
        raw = f"static_{file_path}_{mtime}".encode('utf-8')
        chash = hashlib.sha256(raw).hexdigest()
        cache_file = os.path.join(CACHE_DIR, f"{chash}.npz")

        if os.path.exists(cache_file):
            try:
                loaded = np.load(cache_file)
                meta = loaded['meta']
                data = loaded['data']
                return data, meta[0], meta[1], meta[2], meta[3], (meta[4], meta[5]), (meta[6], meta[7])
            except: pass

        try:
            img = Image.open(file_path).convert("RGBA")
            padded_img, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = process_texture_for_opengl(img)
            d_list = np.array(padded_img).flatten()
            
            meta = np.array([orig_w, orig_h, pad_w, pad_h, uv_min[0], uv_min[1], uv_max[0], uv_max[1]], dtype=np.float32)
            np.savez_compressed(cache_file, data=d_list, meta=meta)
            return d_list, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max
        except: return None

    # Entirely decoupled from Jump-Flood padding to avoid OS cast panics.
    def load_flag_textures(self):
        if not HAS_IMG_LIBS: return
        flag_factions = [
            "Independent", "Hegemony", "Sindrian Diktat", "Persean League", 
            "Tritachyon", "Luddic Church", "Pirates", "Luddic Path"
        ]
        for fac_name in flag_factions:
            fname = fac_name.replace(" ", "_") + ".png"
            path = os.path.join(FLAGS_DIR, fname)
            if os.path.exists(path):
                try:
                    img = Image.open(path).convert("RGBA")
                    w, h = img.size
                    if w > 256:
                        ratio = 256 / w
                        h = int(h * ratio)
                        w = 256
                        img = img.resize((w, h), Image.LANCZOS)
                        
                    flat_data = (np.array(img).astype(np.float32) / 255.0).flatten()
                    tag = f"flag_tex_{fac_name}"
                    if dpg.does_item_exist(tag): dpg.delete_item(tag)
                    dpg.add_static_texture(width=w, height=h, default_value=flat_data, tag=tag, parent="main_texture_registry")
                    self.loaded_flags[fac_name] = {"tag": tag, "w": w, "h": h, "pad_w": w, "pad_h": h, "uv_min": (0.0, 0.0), "uv_max": (1.0, 1.0)}
                except Exception as e:
                    pass

    def scan_virtual_filesystem(self):
        self.virtual_file_map = {}
        self.available_roots = []
        if not os.path.exists(DATA_DIR): return
        roots = [d for d in os.listdir(DATA_DIR) if os.path.isdir(os.path.join(DATA_DIR, d))]
        roots.sort()
        self.available_roots = roots

        for root_name in roots:
            root_path = os.path.join(DATA_DIR, root_name)
            for dirpath, dirnames, filenames in os.walk(root_path):
                for f in filenames:
                    if f.lower().endswith(".png"):
                        full_path = os.path.join(dirpath, f)
                        rel_path = os.path.relpath(full_path, root_path).replace("\\", "/")
                        if rel_path not in self.virtual_file_map:
                            self.virtual_file_map[rel_path] = []
                        self.virtual_file_map[rel_path].append(root_name)

    def get_active_root_for_file(self, virtual_path):
        available = self.virtual_file_map.get(virtual_path, [])
        if not available: return None
        saved = self.active_roots.get(virtual_path)
        if saved and saved in available: return saved
        pref = self.state.get("preferred_root", "graphics")
        if pref in available: return pref
        return available[0]
    
    def get_setting_key(self):
        if self.current_viewing_root and self.current_virtual_path:
            return f"{self.current_viewing_root}/{self.current_virtual_path}"
        return None

    def process_image_data(self, pil_image, settings, cache_key=None):
        if not HAS_IMG_LIBS: return np.array([]), 0, 0, 0, 0, (0.0, 0.0), (1.0, 1.0)
        
        needs_structural_recalc = settings.get("chroma_enabled", False) or settings.get("filter_edges", False)
        use_fast_path = (cache_key is not None) and not needs_structural_recalc

        if use_fast_path:
            if cache_key not in self.padded_base_cache:
                padded_img, ow, oh, pw, ph, umin, umax = process_texture_for_opengl(pil_image.copy().convert("RGBA"))
                self.padded_base_cache[cache_key] = (padded_img, ow, oh, pw, ph, umin, umax)
            
            cached_pad, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = self.padded_base_cache[cache_key]
            img = cached_pad.copy()
        else:
            img = pil_image.copy().convert("RGBA")
            if settings.get("chroma_enabled", False):
                target = settings.get("chroma_target", [0, 255, 0, 255])
                replace = settings.get("chroma_replace", [0, 0, 0, 0])
                tol = settings.get("chroma_tol", 50.0)
                arr = np.array(img)
                t_rgb = np.array(target[:3])
                diff = arr[:, :, :3] - t_rgb
                dist = np.linalg.norm(diff, axis=2)
                mask = dist < tol
                arr[mask] = replace
                img = Image.fromarray(arr)

            if settings.get("filter_edges", False):
                r, g, b, a = img.split()
                rgb = Image.merge("RGB", (r,g,b)).filter(ImageFilter.FIND_EDGES)
                r, g, b = rgb.split()
                img = Image.merge("RGBA", (r,g,b,a))

            padded_img, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = process_texture_for_opengl(img)
            img = padded_img 

        if settings.get("filter_grayscale", False): img = ImageEnhance.Color(img).enhance(0.0)
        if settings.get("filter_invert", False):
            r, g, b, a = img.split()
            img = Image.merge("RGBA", (ImageOps.invert(r), ImageOps.invert(g), ImageOps.invert(b), a))

        g = self.state.get("texture_global_adjustments", {"h":0,"s":0,"v":0})
        s_val = max(0.0, settings.get("s", 1.0) + g["s"])
        v_val = max(0.0, settings.get("v", 1.0) + g["v"])
        h_val = settings.get("h", 0.0) + g["h"]
        c_val = settings.get("contrast", 1.0) 
        gamma_val = settings.get("gamma", 1.0)

        if s_val != 1.0: img = ImageEnhance.Color(img).enhance(s_val)
        if v_val != 1.0: img = ImageEnhance.Brightness(img).enhance(v_val)
        if c_val != 1.0: img = ImageEnhance.Contrast(img).enhance(c_val) 
        if gamma_val != 1.0 and gamma_val > 0.01:
            inv_gamma = 1.0 / gamma_val
            table = [int(((i / 255.0) ** inv_gamma) * 255) for i in range(256)]
            r, g, b, a = img.split()
            r = r.point(table)
            g = g.point(table)
            b = b.point(table)
            img = Image.merge("RGBA", (r, g, b, a))

        if h_val != 0.0:
            img_hsv = img.convert("HSV")
            h, s, v = img_hsv.split()
            np_h = np.array(h, dtype=int)
            shift_amt = int(h_val * 255)
            np_h = (np_h + shift_amt) % 255
            h_new = Image.fromarray(np_h.astype('uint8'), 'L')
            img_hsv = Image.merge("HSV", (h_new, s, v))
            r, g, b = img_hsv.convert("RGB").split()
            a = img.split()[3]
            img = Image.merge("RGBA", (r, g, b, a))

        alpha_scale = settings.get("a", 1.0)
        if alpha_scale != 1.0:
            r, g, b, a = img.split()
            np_a = np.array(a, dtype=float) * settings["a"]
            np_a = np.clip(np_a, 0, 255).astype('uint8')
            img = Image.merge("RGBA", (r, g, b, Image.fromarray(np_a, 'L')))

        if settings.get("tint_enabled", False):
            if "tint_color" in settings:
                 tc = settings["tint_color"]
                 if tc[0] < 250 or tc[1] < 250 or tc[2] < 250:
                     tr, tg, tb = tc[0]/255.0, tc[1]/255.0, tc[2]/255.0
                     arr = np.array(img).astype(float)
                     arr[:, :, 0] *= tr
                     arr[:, :, 1] *= tg
                     arr[:, :, 2] *= tb
                     img = Image.fromarray(arr.astype('uint8'))

        arr = np.array(img)
        alpha_mask = arr[:, :, 3] > 0
        noise_amt = settings.get("noise", 0.0)
        scan_strength = settings.get("scanlines", 0.0)

        if noise_amt > 0.0:
            strength = int(noise_amt * 100)
            noise = np.random.randint(-strength, strength + 1, arr[:, :, :3].shape)
            rgb = arr[:, :, :3].astype(int)
            rgb[alpha_mask] += noise[alpha_mask]
            np.clip(rgb, 0, 255, out=rgb)
            arr[:, :, :3] = rgb.astype('uint8')
        if scan_strength > 0.0:
            mult = np.ones(arr.shape[:2], dtype=float)
            mult[::2, :] = 1.0 - scan_strength
            rgb = arr[:, :, :3].astype(float)
            rgb *= mult[:, :, np.newaxis]
            arr[:, :, :3] = rgb.astype('uint8')
            
        final_data = arr.flatten()
        return final_data, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max

    def load_texture_to_lab(self, virtual_path):
        if not HAS_IMG_LIBS: return
        if self.current_virtual_path:
            old_tag = f"file_btn_{self.current_virtual_path}"
            if dpg.does_item_exist(old_tag):
                label = dpg.get_item_configuration(old_tag).get("label", "")
                if label and label.startswith("[!]"):
                    dpg.bind_item_theme(old_tag, "rec_file_theme")
                else:
                    dpg.bind_item_theme(old_tag, 0)
        self.current_virtual_path = virtual_path
        if self.selected_file_theme:
            new_tag = f"file_btn_{virtual_path}"
            if dpg.does_item_exist(new_tag):
                dpg.bind_item_theme(new_tag, self.selected_file_theme)
        
        active_root = self.get_active_root_for_file(virtual_path)
        self.current_viewing_root = active_root
        self._load_image_internal()
        self.update_source_controls()

    def _load_image_internal(self):
        if not self.current_virtual_path or not self.current_viewing_root: return
        full_path = os.path.join(DATA_DIR, self.current_viewing_root, self.current_virtual_path)
        cache_key = f"{self.current_viewing_root}/{self.current_virtual_path}"
        
        if cache_key not in self.base_image_cache:
            try:
                self.base_image_cache[cache_key] = Image.open(full_path)
            except Exception as e:
                self._set_status(f"Error loading image: {e}", [255,0,0])
                return

        setting_key = self.get_setting_key()
        if setting_key not in self.texture_settings:
            self.texture_settings[setting_key] = {
                "h": 0.0, "s": 1.0, "v": 1.0, "a": 1.0, 
                "contrast": 1.0, "gamma": 1.0, "noise": 0.0, "scanlines": 0.0,
                "tint_enabled": False, "tint_color": [255, 255, 255, 255],
                "chroma_enabled": False, "chroma_target": [0, 255, 0, 255],
                "chroma_replace": [0, 0, 0, 0], "chroma_tol": 50.0,
                "filter_grayscale": False, "filter_invert": False, "filter_edges": False
            }
            
        s = self.texture_settings[setting_key]
        dpg.set_value("tex_h", s.get("h", 0.0))
        dpg.set_value("tex_s", s.get("s", 1.0))
        dpg.set_value("tex_v", s.get("v", 1.0))
        dpg.set_value("tex_a", s.get("a", 1.0))
        dpg.set_value("tex_contrast", s.get("contrast", 1.0))
        dpg.set_value("tex_gamma", s.get("gamma", 1.0))
        dpg.set_value("tex_noise", s.get("noise", 0.0))
        dpg.set_value("tex_scanlines", s.get("scanlines", 0.0))
        dpg.set_value("tex_tint_enabled", s.get("tint_enabled", False))
        dpg.set_value("tex_tint_picker", s.get("tint_color", [255, 255, 255, 255]))
        dpg.set_value("chroma_enabled", s.get("chroma_enabled", False))
        dpg.set_value("chroma_target", s.get("chroma_target", [0, 255, 0, 255]))
        dpg.set_value("chroma_replace", s.get("chroma_replace", [0, 0, 0, 0]))
        dpg.set_value("chroma_tol", s.get("chroma_tol", 50.0))
        dpg.set_value("filter_grayscale", s.get("filter_grayscale", False))
        dpg.set_value("filter_invert", s.get("filter_invert", False))
        dpg.set_value("filter_edges", s.get("filter_edges", False))

        if dpg.does_item_exist("preview_label"):
            dpg.set_value("preview_label", f"Viewing: {self.current_virtual_path}")
        
        self.refresh_texture_preview()

    def sync_layer_texture(self, virtual_path, force_shm=False):
        if not HAS_IMG_LIBS: return
        try:
            active_root = self.get_active_root_for_file(virtual_path)
            if not active_root: return
            
            cache_key = f"{active_root}/{virtual_path}"
            full_path = os.path.join(DATA_DIR, active_root, virtual_path)
            settings = self.texture_settings.get(cache_key, {})

            # Safe init for local float cache
            if not hasattr(self, "dpg_float_cache"): self.dpg_float_cache = {}
            
            # Lazy-load image to prevent cache misses
            if cache_key not in getattr(self, "base_image_cache", {}):
                if not hasattr(self, "base_image_cache"): self.base_image_cache = {}
                if os.path.exists(full_path): 
                    self.base_image_cache[cache_key] = Image.open(full_path).convert("RGBA")
                else: return
            
            cached = self._check_cache(full_path, settings)
            if cached:
                data_list, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = cached
            else:
                data_list, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = self.process_image_data(self.base_image_cache[cache_key], settings, cache_key)
                self._save_cache(full_path, settings, data_list, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max)
                
            dyn_tag = f"live_layer_{virtual_path}"
            
            # Use your built-in robust cache generator for the true state hash
            true_hash = self._get_cache_hash(full_path, settings) or "fallback_hash"
            
            # Main Thread Optimization: Use the true_hash so we actually detect changes
            if getattr(self, f"_last_hash_{virtual_path}", None) != true_hash or force_shm:
                self.dpg_float_cache[virtual_path] = (data_list.astype(np.float32) / 255.0)
                setattr(self, f"_last_hash_{virtual_path}", true_hash)
                
            dpg_data = self.dpg_float_cache[virtual_path]
            
            if dpg.does_alias_exist(dyn_tag):
                if self.live_preview_custom_tex.get(virtual_path, {}).get("pad_w") != pad_w or self.live_preview_custom_tex.get(virtual_path, {}).get("pad_h") != pad_h:
                    if dpg.does_item_exist("live_preview_drawlist"): dpg.delete_item("live_preview_drawlist", children_only=True)
                    dpg.delete_item(dyn_tag)
                    dpg.add_dynamic_texture(width=int(pad_w), height=int(pad_h), default_value=dpg_data, tag=dyn_tag, parent="main_texture_registry")
                else:
                    dpg.set_value(dyn_tag, dpg_data)
            else:
                dpg.add_dynamic_texture(width=int(pad_w), height=int(pad_h), default_value=dpg_data, tag=dyn_tag, parent="main_texture_registry")
                
            self.live_preview_custom_tex[virtual_path] = {"w": orig_w, "h": orig_h, "pad_w": pad_w, "pad_h": pad_h, "uv_min": uv_min, "uv_max": uv_max}
            
            # IPC Optimization: Actually push updates to the Pop-Out window
            if self.popout_process and self.popout_process.is_alive():
                if getattr(self, f"_last_ipc_hash_{virtual_path}", None) != true_hash or force_shm:
                    shm_name = self.shm_manager.write(f"shm_{dyn_tag}", data_list)
                    self.popout_queue.put({
                        "type": "tex_shm", "id": virtual_path, "shm_name": shm_name,
                        "size": data_list.size, "pad_w": int(pad_w), "pad_h": int(pad_h),
                        "orig_w": orig_w, "orig_h": orig_h, "uv_min": uv_min, "uv_max": uv_max
                    })
                    setattr(self, f"_last_ipc_hash_{virtual_path}", true_hash)
                    
        except Exception as e:
            print(f"Live preview sync error for {virtual_path}: {e}")

    def refresh_texture_preview(self, sender=None, app_data=None):
        if not self.current_virtual_path or not HAS_IMG_LIBS: return
        
        if sender == "preview_zoom":
            if dpg.does_item_exist("preview_image_item"):
                 zoom = dpg.get_value("preview_zoom")
                 dpg.configure_item("preview_image_item", width=int(self.tex_w * zoom), height=int(self.tex_h * zoom))
            return

        setting_key = self.get_setting_key()
        if not setting_key: return
        settings = self.texture_settings[setting_key]
        
        settings["h"] = dpg.get_value("tex_h")
        settings["s"] = dpg.get_value("tex_s")
        settings["v"] = dpg.get_value("tex_v")
        settings["a"] = dpg.get_value("tex_a")
        settings["contrast"] = dpg.get_value("tex_contrast")
        settings["gamma"] = dpg.get_value("tex_gamma")
        settings["noise"] = dpg.get_value("tex_noise")
        settings["scanlines"] = dpg.get_value("tex_scanlines")
        settings["tint_enabled"] = dpg.get_value("tex_tint_enabled")
        settings["tint_color"] = [int(x) for x in dpg.get_value("tex_tint_picker")]
        settings["chroma_enabled"] = dpg.get_value("chroma_enabled")
        settings["chroma_target"] = [int(x) for x in dpg.get_value("chroma_target")]
        settings["chroma_replace"] = [int(x) for x in dpg.get_value("chroma_replace")]
        settings["chroma_tol"] = dpg.get_value("chroma_tol")
        settings["filter_grayscale"] = dpg.get_value("filter_grayscale")
        settings["filter_invert"] = dpg.get_value("filter_invert")
        settings["filter_edges"] = dpg.get_value("filter_edges")
        
        self.save_tool_state()
        cache_key = f"{self.current_viewing_root}/{self.current_virtual_path}"
        if cache_key not in self.base_image_cache: return
        full_path = os.path.join(DATA_DIR, self.current_viewing_root, self.current_virtual_path)

        try:
            cached = self._check_cache(full_path, settings)
            if cached:
                data_list, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = cached
            else:
                data_list, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = self.process_image_data(self.base_image_cache[cache_key], settings, cache_key)
                self._save_cache(full_path, settings, data_list, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max)
                
            tag = "preview_texture_dynamic"
            dpg_data = (data_list.astype(np.float32) / 255.0)

            if dpg.does_item_exist(tag):
                if getattr(self, "tex_pad_w", 0) != pad_w or getattr(self, "tex_pad_h", 0) != pad_h:
                    if dpg.does_item_exist("preview_image_item"):
                        dpg.configure_item("preview_image_item", texture_tag="static_void_texture")
                    dpg.delete_item(tag)
                    dpg.add_dynamic_texture(width=int(pad_w), height=int(pad_h), default_value=dpg_data, tag=tag, parent="main_texture_registry")
                    self.tex_w = orig_w
                    self.tex_h = orig_h
                    self.tex_pad_w = pad_w
                    self.tex_pad_h = pad_h
                else:
                    dpg.set_value(tag, dpg_data)
            else:
                dpg.add_dynamic_texture(width=int(pad_w), height=int(pad_h), default_value=dpg_data, tag=tag, parent="main_texture_registry")
                self.tex_w = orig_w
                self.tex_h = orig_h
                self.tex_pad_w = pad_w
                self.tex_pad_h = pad_h

            zoom = dpg.get_value("preview_zoom") if dpg.does_item_exist("preview_zoom") else 1.0
            if dpg.does_item_exist("preview_image_item"):
                dpg.configure_item("preview_image_item", texture_tag=tag, width=int(orig_w * zoom), height=int(orig_h * zoom), uv_min=uv_min, uv_max=uv_max)
                
            active_export_root = self.get_active_root_for_file(self.current_virtual_path)
            if self.current_viewing_root == active_export_root:
                self.sync_layer_texture(self.current_virtual_path)
                self.refresh_live_preview()
            
        except Exception as e:
            self._set_status(f"Tex Error: {str(e)}", [255, 0, 0])

    def populate_file_list(self, filter_text=""):
        dpg.delete_item("file_list_group", children_only=True)
        if not os.path.exists(DATA_DIR):
            dpg.add_text("Data folder missing!", parent="file_list_group", color=[255,0,0])
            return
        
        self.scan_virtual_filesystem()
        recommended = []
        if os.path.exists(RECOMMENDED_IMPORT_FILE):
            try:
                with open(RECOMMENDED_IMPORT_FILE, 'r') as f:
                    rec_data = json.load(f)
                    recommended = rec_data.get("Recommended_Import", [])
            except: pass
            
        grouped_files = {}      
        for v_path in self.virtual_file_map.keys():
            if filter_text and filter_text.lower() not in v_path.lower(): continue          
            folder = os.path.dirname(v_path)
            if not folder: folder = "Root"
            if folder not in grouped_files: grouped_files[folder] = []
            grouped_files[folder].append(v_path)           
            
        for folder in sorted(grouped_files.keys()):
            with dpg.collapsing_header(label=folder, parent="file_list_group", default_open=False):
                def sort_key(vp): return (0 if vp in recommended else 1, vp)
                for v_path in sorted(grouped_files[folder], key=sort_key):
                    fname = os.path.basename(v_path)
                    roots = self.virtual_file_map[v_path]
                    label = fname                    
                    is_rec = v_path in recommended
                    if is_rec: label = f"[!] {label}"
                    if len(roots) > 1: label += f" ({len(roots)})"                  
                    
                    btn_tag = f"file_btn_{v_path}"
                    dpg.add_button(label=label, width=-1, tag=btn_tag, callback=lambda s, a, u: self.load_texture_to_lab(u), user_data=v_path)                  
                    if self.current_virtual_path == v_path and self.selected_file_theme: dpg.bind_item_theme(btn_tag, self.selected_file_theme)
                    elif is_rec: dpg.bind_item_theme(btn_tag, "rec_file_theme")

    def filter_textures(self, sender, app_data):
        self.populate_file_list(app_data)

    def update_source_controls(self):
        if not self.current_virtual_path:
            dpg.configure_item("source_selector_group", show=False)
            return
        available_roots = self.virtual_file_map.get(self.current_virtual_path, [])
        if len(available_roots) <= 1:
            dpg.configure_item("source_selector_group", show=False)
            return
        dpg.configure_item("source_selector_group", show=True)
        dpg.set_value("source_label_display", f"Source: [{self.current_viewing_root}]")
        active_export_root = self.get_active_root_for_file(self.current_virtual_path)
        dpg.set_value("source_active_checkbox", self.current_viewing_root == active_export_root)

    def cycle_source_root(self, sender, app_data, direction):
        if not self.current_virtual_path: return
        available = self.virtual_file_map.get(self.current_virtual_path, [])
        if not available: return
        try: curr_idx = available.index(self.current_viewing_root)
        except ValueError: curr_idx = 0
        self.current_viewing_root = available[(curr_idx + direction) % len(available)]
        self._load_image_internal()
        self.update_source_controls()

    def set_active_export_source(self, sender, app_data):
        if not self.current_virtual_path: return
        if app_data: self.active_roots[self.current_virtual_path] = self.current_viewing_root
        else: dpg.set_value("source_active_checkbox", True)
        self.save_tool_state()
        self.sync_layer_texture(self.current_virtual_path)
        self.refresh_live_preview()

    def reset_current_texture(self):
        if not self.current_virtual_path: return
        setting_key = self.get_setting_key()
        self.texture_settings[setting_key] = {
            "h": 0.0, "s": 1.0, "v": 1.0, "a": 1.0, 
            "contrast": 1.0, "gamma": 1.0, "noise": 0.0, "scanlines": 0.0,
            "tint_enabled": False, "tint_color": [255, 255, 255, 255],
            "chroma_enabled": False, "chroma_target": [0, 255, 0, 255],
            "chroma_replace": [0, 0, 0, 0], "chroma_tol": 50.0,
            "filter_grayscale": False, "filter_invert": False, "filter_edges": False
        }
        self._load_image_internal()
        active_root = self.get_active_root_for_file(self.current_virtual_path)
        if self.current_viewing_root == active_root:
            self.sync_layer_texture(self.current_virtual_path)
            self.refresh_live_preview()
        self._set_status("Current Texture Version Reset.", [255, 200, 0])

    def apply_current_to_all(self, sender=None, app_data=None):
        if not self.current_virtual_path: return
        setting_key = self.get_setting_key()
        current = self.texture_settings.get(setting_key)
        if not current: return
        count = 0
        for key in self.texture_settings.keys():
            self.texture_settings[key] = copy.deepcopy(current)
            count += 1
        if dpg.does_item_exist("apply_all_confirm"):
            dpg.configure_item("apply_all_confirm", show=False)
            self.active_anchor_window = None
        self.refresh_live_preview()
        self._set_status(f"Applied settings to {count} loaded textures.", [0, 255, 0])

    def switch_view(self, sender, app_data, user_data):
        dpg.configure_item("group_config_editor", show=False)
        dpg.configure_item("group_texture_lab", show=False)
        dpg.configure_item("group_faction_editor", show=False)
        if user_data == "config": dpg.configure_item("group_config_editor", show=True)
        elif user_data == "texture": dpg.configure_item("group_texture_lab", show=True)
        elif user_data == "faction": dpg.configure_item("group_faction_editor", show=True)

    def toggle_faction_key_active(self, sender, app_data, user_data):
        fname, key = user_data
        is_active = app_data
        active_list = self.state["active_faction_keys"].get(fname, [])
        if is_active and key not in active_list: active_list.append(key)
        elif not is_active and key in active_list: active_list.remove(key)
        self.state["active_faction_keys"][fname] = active_list
        self.save_tool_state()

    def open_faction_color_editor(self, sender, app_data, user_data):
        fname, key = user_data
        current_val = self.state["current_faction_colors"].get(fname, {}).get(key)
        dpg.configure_item("shared_color_picker", callback=self.faction_color_picker_cb, user_data=(fname, key))
        dpg.set_value("shared_color_picker", current_val)
        dpg.set_value("shared_editor_title", f"FACTION: {fname}")
        dpg.set_value("shared_editor_desc", f"Editing {key} for {fname}")
        self.toggle_anchored_window("shared_color_editor", sender)

    def faction_color_picker_cb(self, sender, app_data, user_data):
        fname, key = user_data
        new_val = [int(round(x * 255)) for x in app_data]
        self.state["current_faction_colors"][fname][key] = new_val
        self.save_tool_state()
        if dpg.does_item_exist(f"btn_fac_{fname}_{key}"): dpg.configure_item(f"btn_fac_{fname}_{key}", default_value=new_val)
        self.draw_faction_preview()

    def resize_windows(self, sender, app_data):
        w, h = app_data[0], app_data[1]
        dpg.configure_item("Main", width=w, height=h)
        tex_right_w = w - 280 - 40
        tex_h = h - 135 
        cfg_h = h - 135
        if dpg.does_item_exist("cfg_col_left"): dpg.configure_item("cfg_col_left", height=cfg_h)
        if dpg.does_item_exist("cfg_col_right"): dpg.configure_item("cfg_col_right", width=max(100, w - 640), height=cfg_h)
        if dpg.does_item_exist("tex_col_left"): dpg.configure_item("tex_col_left", height=tex_h)
        if dpg.does_item_exist("tex_col_right"): dpg.configure_item("tex_col_right", width=max(100, tex_right_w), height=tex_h)
        if dpg.does_item_exist("fac_col_left"): dpg.configure_item("fac_col_left", height=cfg_h)
        if dpg.does_item_exist("fac_col_right"): dpg.configure_item("fac_col_right", width=max(100, w - 640), height=cfg_h)
        if self.current_virtual_path: self.refresh_texture_preview()

    def toggle_scroll_zoom(self, sender, app_data):
        self.state["enable_scroll_zoom"] = app_data
        self.save_tool_state()

    def on_mouse_wheel(self, sender, app_data):
        if not self.state.get("enable_scroll_zoom", True): return
        if dpg.is_item_hovered("live_preview_drawlist") or dpg.is_item_hovered("live_preview_container"):
            if dpg.does_item_exist("live_preview_zoom"):
                curr = dpg.get_value("live_preview_zoom")
                new_zoom = max(0.2, min(3.0, curr + (app_data * 0.1)))
                dpg.set_value("live_preview_zoom", new_zoom)
                self.refresh_live_preview()

    def minimize_window(self): dpg.minimize_viewport()
    def toggle_fullscreen(self): dpg.toggle_viewport_fullscreen()
    def close_app(self): dpg.stop_dearpygui()

    def slot_load_click(self, sender, app_data, slot_idx):
        saved = self.quick_copy_slots[slot_idx]
        setting_key = self.get_setting_key()
        if saved and setting_key:
            self.texture_settings[setting_key] = copy.deepcopy(saved)
            self._load_image_internal()
            self._set_status(f"Applied Slot {slot_idx+1}", [0, 255, 0])

    def slot_save_click(self, sender, app_data, slot_idx):
        setting_key = self.get_setting_key()
        if setting_key and setting_key in self.texture_settings:
            self.quick_copy_slots[slot_idx] = copy.deepcopy(self.texture_settings[setting_key])
            s = self.quick_copy_slots[slot_idx]
            c = s.get("tint_color", [255, 255, 255, 255])
            v_mult = s.get("v", 1.0)
            color = [min(255, c[0]*v_mult), min(255, c[1]*v_mult), min(255, c[2]*v_mult), 255]
            dpg.configure_item(f"slot_btn_{slot_idx}", label=f"{slot_idx+1}")
            dpg.bind_item_theme(f"slot_btn_{slot_idx}", self.create_colored_theme(color))
            self._set_status(f"Saved to Slot {slot_idx+1}", [0, 255, 0])

    def create_colored_theme(self, color):
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Button, color, category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [min(255, c+20) for c in color], category=dpg.mvThemeCat_Core)
                lum = (0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2])
                txt = [0,0,0,255] if lum > 128 else [255,255,255,255]
                dpg.add_theme_color(dpg.mvThemeCol_Text, txt, category=dpg.mvThemeCat_Core)
        return t

    def update_texture_globals(self, sender, app_data, user_data):
        h = dpg.get_value("adj_all_h")
        s = dpg.get_value("adj_all_s")
        v = dpg.get_value("adj_all_v")
        self.state["texture_global_adjustments"] = {"h": h, "s": s, "v": v}
        self.save_tool_state()
        if self.current_virtual_path: self.refresh_texture_preview()

    def reset_texture_globals(self, sender=None, app_data=None, user_data=None):
        dpg.set_value("adj_all_h", 0.0)
        dpg.set_value("adj_all_s", 0.0)
        dpg.set_value("adj_all_v", 0.0)
        self.state["texture_global_adjustments"] = {"h": 0.0, "s": 0.0, "v": 0.0}
        self.save_tool_state()
        if self.current_virtual_path: self.refresh_texture_preview()
        self._set_status("Texture Global Adjustments Reset...", [255, 210, 0])

    def restore_all_textures(self, sender=None, app_data=None):
        self.texture_settings = {}
        self.active_roots = {}
        self.state["texture_global_adjustments"] = {"h": 0.0, "s": 0.0, "v": 0.0}
        if dpg.does_item_exist("adj_all_h"): dpg.set_value("adj_all_h", 0.0)
        if dpg.does_item_exist("adj_all_s"): dpg.set_value("adj_all_s", 0.0)
        if dpg.does_item_exist("adj_all_v"): dpg.set_value("adj_all_v", 0.0)
        self.save_tool_state()
        if self.current_virtual_path:
            new_root = self.get_active_root_for_file(self.current_virtual_path)
            if new_root: self.current_viewing_root = new_root
            self.update_source_controls()
            self._load_image_internal()
        if dpg.does_item_exist("restore_all_tex_confirm"):
             dpg.configure_item("restore_all_tex_confirm", show=False)
             self.active_anchor_window = None
        self.refresh_live_preview()
        self._set_status("All UI Elements Reset to Default...", [255,200,0])

    def toggle_anchored_window(self, window_tag, source_item_tag):
        if not dpg.does_item_exist(window_tag) or not dpg.does_item_exist(source_item_tag): return
        if dpg.is_item_shown(window_tag):
            dpg.configure_item(window_tag, show=False)
            self.active_anchor_window = None
            self.active_anchor_button = None
            return
        if self.active_anchor_window and self.active_anchor_window != window_tag: dpg.configure_item(self.active_anchor_window, show=False)
        state = dpg.get_item_state(source_item_tag)
        rect_min = state["rect_min"] 
        rect_size = state["rect_size"] 
        win_h = dpg.get_item_height(window_tag)
        if win_h < 50: win_h = 300 
        viewport_h = dpg.get_viewport_height()
        target_x = rect_min[0]
        target_y = rect_min[1] + rect_size[1] + 5 
        if target_y + win_h > (viewport_h - 50): target_y = rect_min[1] - win_h - 5
        dpg.configure_item(window_tag, pos=[target_x, target_y], show=True)
        dpg.focus_item(window_tag)
        self.active_anchor_window = window_tag
        self.active_anchor_button = source_item_tag

    def toggle_adjust_all_window(self, sender, app_data):
        vals = self.state.get("texture_global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})
        dpg.set_value("adj_all_h", vals["h"])
        dpg.set_value("adj_all_s", vals["s"])
        dpg.set_value("adj_all_v", vals["v"])
        self.toggle_anchored_window("adjust_all_window", sender)

    def close_adjust_all_window(self):
        self.save_tool_state()
        dpg.configure_item("adjust_all_window", show=False)

    def toggle_restore_modal(self, sender, app_data): self.toggle_anchored_window("confirm_modal", sender)
    def toggle_restore_all_tex_modal(self, sender, app_data): self.toggle_anchored_window("restore_all_tex_confirm", sender)
    def toggle_apply_all_confirm_modal(self, sender, app_data): self.toggle_anchored_window("apply_all_confirm", sender)
    def toggle_restore_factions_modal(self, sender, app_data): self.toggle_anchored_window("restore_factions_confirm", sender)

    def toggle_global_window(self, sender, app_data):
        vals = self.state.get("global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})
        dpg.set_value("global_h", vals["h"])
        dpg.set_value("global_s", vals["s"])
        dpg.set_value("global_v", vals["v"])
        self.toggle_anchored_window("global_window", sender)

    def open_color_editor(self, sender, app_data, user_data):
        category, sk = user_data
        current_val = self.state["current_colors"].get(category, {}).get(sk)
        dpg.set_value("shared_color_picker", current_val)
        dpg.set_value("shared_editor_title", f"EDITING: {sk}")
        desc = self.color_descriptions.get(sk, "No description available.")
        dpg.set_value("shared_editor_desc", desc)
        dpg.configure_item("shared_color_picker", callback=self.color_cb, user_data=(category, sk))
        self.toggle_anchored_window("shared_color_editor", sender)

    def update_rec_color(self, sender, app_data):
        new_val = []
        for x in app_data[:4]:
            if isinstance(x, float) and x <= 1.0: new_val.append(int(round(x * 255)))
            else: new_val.append(int(x))
        new_val = [max(0, min(255, v)) for v in new_val]
        self.state["rec_color"] = new_val
        self.save_tool_state()
        if dpg.does_item_exist("rec_file_theme_color"): dpg.set_value("rec_file_theme_color", new_val)

    def on_global_click(self, sender, app_data):
        if not self.active_anchor_window or not dpg.does_item_exist(self.active_anchor_window): return
        if not dpg.is_item_shown(self.active_anchor_window): 
            self.active_anchor_window = None
            self.active_anchor_button = None
            return
        if self.active_anchor_button and dpg.does_item_exist(self.active_anchor_button) and dpg.is_item_hovered(self.active_anchor_button): return
        try:
            mouse_pos = dpg.get_mouse_pos(local=False) 
            w_pos = dpg.get_item_pos(self.active_anchor_window)
            w_width = dpg.get_item_width(self.active_anchor_window)
            w_height = dpg.get_item_height(self.active_anchor_window)
            if (w_pos[0] <= mouse_pos[0] <= w_pos[0] + w_width) and (w_pos[1] <= mouse_pos[1] <= w_pos[1] + w_height): return
        except: pass
        if dpg.is_item_hovered(self.active_anchor_window): return
        dpg.configure_item(self.active_anchor_window, show=False)
        self.active_anchor_window = None
        self.active_anchor_button = None

    def set_preferred_root(self, sender, app_data, user_data):
        self.state["preferred_root"] = app_data
        self.save_tool_state()
        
        if os.path.exists(LAYERS_JSON_FILE):
            try:
                with open(LAYERS_JSON_FILE, 'r') as f: layers = json.load(f)
                for layer in layers.values():
                    if not layer.get("is_color_mask", False):
                        vf = layer.get("texture_file", "")
                        if vf: self.sync_layer_texture(vf)
            except: pass
            
        if self.current_virtual_path:
            new_root = self.get_active_root_for_file(self.current_virtual_path)
            if new_root:
                self.current_viewing_root = new_root
                self.update_source_controls()
                self._load_image_internal()
                
        self.refresh_live_preview()

    def _open_file_dialog(self, is_dir=False, filetypes=None):
        try:
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True) 
            if is_dir: path = filedialog.askdirectory(title="Select Folder")
            else:
                if not filetypes: filetypes = [("JSON files", "*.json")]
                path = filedialog.askopenfilename(title="Select File", filetypes=filetypes)
            root.destroy()
            return path
        except Exception as e:
            print(f"Dialog Error: {e}")
            return None

    def _save_file_dialog(self, default_name="Star_UI_Composite.png", filetypes=[("PNG Image", "*.png")]):
        try:
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.asksaveasfilename(
                title="Export Live Preview",
                initialfile=default_name,
                defaultextension=".png",
                filetypes=filetypes
            )
            root.destroy()
            return path
        except Exception as e:
            print(f"Save Dialog Error: {e}")
            return None

    def save_bg_state(self, sender, app_data):
        self.state["live_preview_bg"] = app_data
        self.save_tool_state()
        self.refresh_live_preview()

    def load_live_preview_backgrounds(self):
        bgs = []
        if os.path.exists(BGS_DIR):
            for f in os.listdir(BGS_DIR):
                if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                    bgs.append(f)
                    tag = f"bg_{f}"
                    if not dpg.does_alias_exist(tag):
                        try:
                            w, h, c, d = dpg.load_image(os.path.join(BGS_DIR, f))
                            dpg.add_static_texture(width=w, height=h, default_value=d, tag=tag, parent="main_texture_registry")
                        except: pass
                        
        if dpg.does_item_exist("live_preview_bg"):
            dpg.configure_item("live_preview_bg", items=bgs)
            curr = dpg.get_value("live_preview_bg")
            if curr not in bgs and bgs:
                dpg.set_value("live_preview_bg", bgs[0])
                self.state["live_preview_bg"] = bgs[0]

    def load_live_preview_textures(self, force_shm=False):
        layers = self.get_cached_layers()
        if not layers: return
        
        for key, layer in layers.items():
            if layer.get("disabled", False): continue
            if layer.get("is_color_mask", False):
                mask_file = layer.get("mask_file", "")
                file_path = os.path.join(LAYERS_DIR, mask_file)
                tex_tag = f"tex_mask_{mask_file}"
                if not os.path.exists(file_path): continue
                
                d_list = None
                cached_data = self._get_static_texture_cached(file_path)
                if cached_data is not None:
                    d_list, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = cached_data
                    
                    if not dpg.does_alias_exist(tex_tag):
                        dpg_data = (d_list.astype(np.float32) / 255.0)
                        dpg.add_static_texture(width=int(pad_w), height=int(pad_h), default_value=dpg_data, tag=tex_tag, parent="main_texture_registry")
                        self.live_preview_custom_tex[mask_file] = {"w": orig_w, "h": orig_h, "pad_w": pad_w, "pad_h": pad_h, "uv_min": uv_min, "uv_max": uv_max}

                if (not dpg.does_alias_exist(tex_tag) or force_shm) and d_list is not None:
                    if self.popout_process and self.popout_process.is_alive():
                        shm_name = self.shm_manager.write(f"shm_{tex_tag}", d_list)
                        cached = self.live_preview_custom_tex.get(mask_file, {})
                        self.popout_queue.put({
                            "type": "tex_shm", "id": mask_file, "shm_name": shm_name,
                            "size": d_list.size, "pad_w": int(cached.get("pad_w", 1)), "pad_h": int(cached.get("pad_h", 1)),
                            "orig_w": cached.get("w", 1), "orig_h": cached.get("h", 1), 
                            "uv_min": cached.get("uv_min", (0,0)), "uv_max": cached.get("uv_max", (1,1))
                        })
            else:
                virtual_file = layer.get("texture_file", "")
                if virtual_file:
                    dyn_tag = f"live_layer_{virtual_file}"
                    if not dpg.does_alias_exist(dyn_tag) or force_shm: 
                        self.sync_layer_texture(virtual_file, force_shm=force_shm)

    def clean_dead_preview_tags(self):
        for key in list(self.preview_tags.keys()):
            valid_tags = []
            for tag_info in self.preview_tags[key]:
                if dpg.does_item_exist(tag_info["tag"]): valid_tags.append(tag_info)
            if valid_tags: self.preview_tags[key] = valid_tags
            else: del self.preview_tags[key]

    def draw_live_preview_to(self, drawlist_tag, zoom_tag):
        if not dpg.does_item_exist(drawlist_tag): return
        dpg.delete_item(drawlist_tag, children_only=True)
        
        layers = self.get_cached_layers()
        if not layers:
            dpg.draw_text((20, 20), "ui_Layers.json not found in Star_UI folder.", color=[255, 100, 100, 255], parent=drawlist_tag)
            return
            
        scale = dpg.get_value(zoom_tag) if dpg.does_item_exist(zoom_tag) else 1.0
        cv_w, cv_h = int(1920 * scale), int(1080 * scale)
        dpg.configure_item(drawlist_tag, width=cv_w, height=cv_h)

        bg_mode = dpg.get_value("live_preview_bg")
        if bg_mode:
            bg_tag = f"bg_{bg_mode}"
            if dpg.does_alias_exist(bg_tag): dpg.draw_image(bg_tag, pmin=(0,0), pmax=(cv_w, cv_h), parent=drawlist_tag)
            else: dpg.draw_rectangle((0,0), (cv_w, cv_h), fill=(10,10,12,255), thickness=0, parent=drawlist_tag)
        else:
            dpg.draw_rectangle((0,0), (cv_w, cv_h), fill=(10,10,12,255), thickness=0, parent=drawlist_tag)

        # Cache the sorted keys to stop burning CPU cycles every frame
        if not hasattr(self, "_sorted_layer_keys") or getattr(self, "_last_layer_count", 0) != len(layers):
            self._sorted_layer_keys = sorted(layers.keys())
            self._last_layer_count = len(layers)

        for key in self._sorted_layer_keys:
            layer = layers[key]
            if layer.get("disabled", False): continue
            
            ax, ay = layer["anchor_x"], layer["anchor_y"]
            w, h = layer["mask_width"], layer["mask_height"]
            origin = layer.get("anchor_origin", "top_left")
            stretch_to_mask = layer.get("stretch_to_mask", False)
            color_key = layer.get("color_key", "")
            tint_color = self.get_color(color_key) if color_key else [255, 255, 255, 255]

            is_color_mask = layer.get("is_color_mask", False)
            if is_color_mask:
                mask_file = layer.get("mask_file", "")
                tex_tag = f"tex_mask_{mask_file}"
                cached = self.live_preview_custom_tex.get(mask_file, {})
            else:
                virtual_file = layer.get("texture_file", "")
                tex_tag = f"live_layer_{virtual_file}"
                cached = self.live_preview_custom_tex.get(virtual_file, {})
                
            if not dpg.does_alias_exist(tex_tag): continue

            actual_w, actual_h = w, h
            if not is_color_mask:
                if "w" in cached and "h" in cached:
                    actual_w, actual_h = cached["w"], cached["h"]

            uv_min = cached.get("uv_min", (0.0, 0.0))
            uv_max = cached.get("uv_max", (1.0, 1.0))

            # Flatten the origin math
            box_w, box_h = (w, h) if (layer.get("is_repeating", False) or stretch_to_mask) else ((1920, 1080) if is_color_mask else (actual_w, actual_h))

            if origin == "bottom_right": tx, ty = ax - box_w, ay - box_h
            elif origin == "bottom_left": tx, ty = ax, ay - box_h
            elif origin == "top_right": tx, ty = ax - box_w, ay
            elif origin == "center": tx, ty = ax - (box_w/2.0), ay - (box_h/2.0)
            else: tx, ty = ax, ay

            if is_color_mask:
                p1, p2 = (0, 0), (1920 * scale, 1080 * scale)
                img_item = dpg.draw_image(tex_tag, pmin=p1, pmax=p2, uv_min=uv_min, uv_max=uv_max, color=tint_color, parent=drawlist_tag)
                self.register_preview(color_key, img_item, "color")
            elif layer.get("is_repeating", False):
                vw, vh = actual_w, actual_h 
                if vw == 0 or vh == 0: continue
                curr_y = ty
                max_y = ty + box_h
                while curr_y < max_y:
                    curr_x = tx
                    max_x = tx + box_w
                    while curr_x < max_x:
                        draw_w, draw_h = min(vw, max_x - curr_x), min(vh, max_y - curr_y)
                        uv_max_u, uv_max_v = draw_w / vw, draw_h / vh
                        
                        mapped_u_max = uv_min[0] + (uv_max_u * (uv_max[0] - uv_min[0]))
                        mapped_v_max = uv_min[1] + (uv_max_v * (uv_max[1] - uv_min[1]))
                        
                        p1 = (curr_x * scale, curr_y * scale)
                        p2 = ((curr_x + draw_w) * scale, (curr_y + draw_h) * scale)
                        img_item = dpg.draw_image(tex_tag, pmin=p1, pmax=p2, uv_min=uv_min, uv_max=(mapped_u_max, mapped_v_max), color=tint_color, parent=drawlist_tag)
                        if color_key: self.register_preview(color_key, img_item, "color")
                        curr_x += vw
                    curr_y += vh
            else:
                p1 = (tx * scale, ty * scale)
                p2 = ((tx + box_w) * scale, (ty + box_h) * scale)
                img_item = dpg.draw_image(tex_tag, pmin=p1, pmax=p2, uv_min=uv_min, uv_max=uv_max, color=tint_color, parent=drawlist_tag)
                if color_key: self.register_preview(color_key, img_item, "color")

        if self.popout_process and self.popout_process.is_alive():
            current_time = time.time()
            if not hasattr(self, "last_pop_update") or (current_time - self.last_pop_update) > 0.02:
                
                flat_colors = {}
                for cat, items in self.state["current_colors"].items():
                    for k, v in items.items():
                        flat_colors[k] = v
                
                layer_mtime = getattr(self, '_layers_mtime', 0)
                state_hash = hash((scale, dpg.get_value("live_preview_bg"), layer_mtime, str(flat_colors)))
                
                if not hasattr(self, "last_state_hash") or self.last_state_hash != state_hash:
                    self.last_pop_update = current_time
                    self.last_state_hash = state_hash
                    
                    self.popout_queue.put({
                        "type": "state",
                        "zoom": scale,
                        "bg": dpg.get_value("live_preview_bg"),
                        "layers": layers,
                        "colors": flat_colors
                    })

    def refresh_live_preview(self, sender=None, app_data=None, force_shm=False):
        self.load_live_preview_textures(force_shm=force_shm)
        self.clean_dead_preview_tags()
        self.draw_live_preview_to("live_preview_drawlist", "live_preview_zoom")

    def toggle_popout_preview(self):
        if self.popout_process and self.popout_process.is_alive():
            self.popout_queue.put({"type": "exit"})
            self.popout_process.join(timeout=1.0)
            self._set_status("Remote Viewport Closed.", [255, 200, 0])
            return

        self._set_status("Spawning Remote OS Viewport via IPC...", [100, 255, 200])
        
        t_name = self.state.get("app_theme", "Starsector (Default)")
        t_data = self.themes.get(t_name, {})
        
        self.popout_process = mp.Process(target=popout_process_loop, args=(self.popout_queue, t_data))
        self.popout_process.daemon = True
        self.popout_process.start()
            
        self.refresh_live_preview(force_shm=True)

    def export_live_preview_png(self, sender=None, app_data=None):
        if not HAS_IMG_LIBS:
            self._set_status("ERROR: Pillow (PIL) is not installed.", [255,0,0])
            return
        if not os.path.exists(LAYERS_JSON_FILE):
            self._set_status("ERROR: Layout JSON not found.", [255,0,0])
            return
        out_path = self._save_file_dialog()
        if not out_path:
            self._set_status("Export Cancelled.", [255, 200, 0])
            return
        self._set_status(f"Exporting Composite to {out_path}...", [200, 200, 200])

        try:
            with open(LAYERS_JSON_FILE, 'r') as f: layers = json.load(f)
            canvas = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
            sorted_keys = sorted(layers.keys())

            for key in sorted_keys:
                layer = layers[key]
                if layer.get("disabled", False): continue
                ax, ay = layer["anchor_x"], layer["anchor_y"]
                w, h = layer["mask_width"], layer["mask_height"]
                origin = layer.get("anchor_origin", "top_left")
                stretch_to_mask = layer.get("stretch_to_mask", False)

                color_key = layer.get("color_key", "")
                tint_color = self.get_color(color_key) if color_key else [255, 255, 255, 255]

                actual_w, actual_h = w, h
                if layer.get("is_color_mask", False):
                    file_path = os.path.join(LAYERS_DIR, layer.get("mask_file", ""))
                    if not os.path.exists(file_path): continue
                    img = Image.open(file_path).convert("RGBA")
                else:
                    virtual_path = layer.get("texture_file", "")
                    active_root = self.get_active_root_for_file(virtual_path)
                    if not active_root: continue
                    file_path = os.path.join(DATA_DIR, active_root, virtual_path)
                    if not os.path.exists(file_path): continue
                    
                    img = Image.open(file_path).convert("RGBA")
                    set_key = f"{active_root}/{virtual_path}"
                    if set_key in self.texture_settings:
                        s = self.texture_settings[set_key]
                        
                        if s.get("filter_grayscale", False): img = ImageEnhance.Color(img).enhance(0.0)
                        if s.get("filter_invert", False):
                            r, g, b, a = img.split()
                            img = Image.merge("RGBA", (ImageOps.invert(r), ImageOps.invert(g), ImageOps.invert(b), a))
                        if s.get("filter_edges", False):
                            r, g, b, a = img.split()
                            rgb = Image.merge("RGB", (r,g,b)).filter(ImageFilter.FIND_EDGES)
                            r, g, b = rgb.split()
                            img = Image.merge("RGBA", (r,g,b,a))

                        g = self.state.get("texture_global_adjustments", {"h":0,"s":0,"v":0})
                        s_val = max(0.0, s.get("s", 1.0) + g["s"])
                        v_val = max(0.0, s.get("v", 1.0) + g["v"])
                        h_val = s.get("h", 0.0) + g["h"]
                        c_val = s.get("contrast", 1.0)
                        gamma_val = s.get("gamma", 1.0)

                        if s_val != 1.0: img = ImageEnhance.Color(img).enhance(s_val)
                        if v_val != 1.0: img = ImageEnhance.Brightness(img).enhance(v_val)
                        if c_val != 1.0: img = ImageEnhance.Contrast(img).enhance(c_val) 
                        if gamma_val != 1.0 and gamma_val > 0.01:
                            inv_gamma = 1.0 / gamma_val
                            table = [int(((i / 255.0) ** inv_gamma) * 255) for i in range(256)]
                            r, g, b, a = img.split()
                            r = r.point(table)
                            g = g.point(table)
                            b = b.point(table)
                            img = Image.merge("RGBA", (r, g, b, a))

                        if h_val != 0.0:
                            img_hsv = img.convert("HSV")
                            h_chan, s_chan, v_chan = img_hsv.split()
                            np_h = np.array(h_chan, dtype=int)
                            shift_amt = int(h_val * 255)
                            np_h = (np_h + shift_amt) % 255
                            h_new = Image.fromarray(np_h.astype('uint8'), 'L')
                            img_hsv = Image.merge("HSV", (h_new, s_chan, v_chan))
                            r, g, b = img_hsv.convert("RGB").split()
                            a = img.split()[3]
                            img = Image.merge("RGBA", (r, g, b, a))

                        alpha_scale = s.get("a", 1.0)
                        if alpha_scale != 1.0:
                            r, g, b, a = img.split()
                            np_a = np.array(a, dtype=float) * alpha_scale
                            np_a = np.clip(np_a, 0, 255).astype('uint8')
                            img = Image.merge("RGBA", (r, g, b, Image.fromarray(np_a, 'L')))

                        if s.get("chroma_enabled", False):
                            target = s.get("chroma_target", [0, 255, 0, 255])
                            replace = s.get("chroma_replace", [0, 0, 0, 0])
                            tol = s.get("chroma_tol", 50.0)
                            arr = np.array(img)
                            t_rgb = np.array(target[:3])
                            diff = arr[:, :, :3] - t_rgb
                            dist = np.linalg.norm(diff, axis=2)
                            mask = dist < tol
                            arr[mask] = replace
                            img = Image.fromarray(arr)

                        if s.get("tint_enabled", False):
                            tc = s.get("tint_color", [255, 255, 255, 255])
                            if tc[:3] != [255, 255, 255]:
                                tr, tg, tb = tc[0]/255.0, tc[1]/255.0, tc[2]/255.0
                                arr = np.array(img).astype(float)
                                arr[:, :, 0] *= tr
                                arr[:, :, 1] *= tg
                                arr[:, :, 2] *= tb
                                img = Image.fromarray(arr.astype('uint8'))

                        arr = np.array(img)
                        alpha_mask = arr[:, :, 3] > 0
                        noise_amt = s.get("noise", 0.0)
                        scan_strength = s.get("scanlines", 0.0)

                        if noise_amt > 0.0:
                            strength = int(noise_amt * 100)
                            noise = np.random.randint(-strength, strength + 1, arr[:, :, :3].shape)
                            rgb = arr[:, :, :3].astype(int)
                            rgb[alpha_mask] += noise[alpha_mask]
                            np.clip(rgb, 0, 255, out=rgb)
                            arr[:, :, :3] = rgb.astype('uint8')
                            
                        if scan_strength > 0.0:
                            mult = np.ones(arr.shape[:2], dtype=float)
                            mult[::2, :] = 1.0 - scan_strength
                            rgb = arr[:, :, :3].astype(float)
                            rgb *= mult[:, :, np.newaxis]
                            arr[:, :, :3] = rgb.astype('uint8')
                            
                        img = Image.fromarray(arr)
                    actual_w, actual_h = img.size

                if tint_color != [255, 255, 255, 255] and tint_color != (255, 255, 255, 255):
                    r, g, b, a = img.split()
                    r = r.point(lambda i: i * (tint_color[0] / 255.0))
                    g = g.point(lambda i: i * (tint_color[1] / 255.0))
                    b = b.point(lambda i: i * (tint_color[2] / 255.0))
                    a = a.point(lambda i: i * (tint_color[3] / 255.0))
                    img = Image.merge("RGBA", (r, g, b, a))

                if layer.get("is_repeating", False) or stretch_to_mask: box_w, box_h = w, h
                elif layer.get("is_color_mask", False): box_w, box_h = 1920, 1080
                else: box_w, box_h = actual_w, actual_h

                if origin == "bottom_right": tx, ty = ax - box_w, ay - box_h
                elif origin == "bottom_left": tx, ty = ax, ay - box_h
                elif origin == "top_right": tx, ty = ax - box_w, ay
                elif origin == "center": tx, ty = ax - (box_w/2.0), ay - (box_h/2.0)
                else: tx, ty = ax, ay
                tx, ty = int(round(tx)), int(round(ty))
                box_w, box_h = int(round(box_w)), int(round(box_h))

                if layer.get("is_color_mask", False): canvas.paste(img, (0, 0), img)
                elif layer.get("is_repeating", False):
                    vw, vh = actual_w, actual_h
                    if vw == 0 or vh == 0: continue
                    tiled_layer = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
                    curr_y = 0
                    while curr_y < box_h:
                        curr_x = 0
                        while curr_x < box_w:
                            tiled_layer.paste(img, (curr_x, curr_y), img)
                            curr_x += vw
                        curr_y += vh
                    canvas.paste(tiled_layer, (tx, ty), tiled_layer)
                elif stretch_to_mask:
                    img_resized = img.resize((box_w, box_h), Image.Resampling.LANCZOS)
                    canvas.paste(img_resized, (tx, ty), img_resized)
                else:
                    canvas.paste(img, (tx, ty), img)

            canvas.save(out_path)
            self._set_status(f"Exported Composite to: {out_path}", [0, 255, 0])
        except Exception as e:
            self._set_status(f"Export Failed: {e}", [255, 0, 0])

    # --- FIRST TIME SETUP LOGIC ---
    def select_setup_game_folder(self):
        path = self._open_file_dialog(is_dir=True)
        if path:
            self.setup_game_dir = path
            dpg.set_value("setup_game_path_display", path)
            
            target_graphics = os.path.join(path, "starsector-core", "graphics")
            if os.path.exists(target_graphics):
                dpg.set_value("setup_status", "                                 Valid Starsector Directory Found")
                dpg.configure_item("setup_status", color=[0, 255, 0])
                dpg.configure_item("btn_import_setup", show=True) 
                
                potential_mods = os.path.join(path, "mods")
                if os.path.exists(potential_mods):
                    self.setup_mod_dir = potential_mods
                    dpg.set_value("setup_mod_path_display", potential_mods)
            else:
                dpg.set_value("setup_status", "                            ERROR: Could not find starsector-core/graphics in this directory.")
                dpg.configure_item("setup_status", color=[255, 50, 50])
                dpg.configure_item("btn_import_setup", show=False)

    def select_setup_mod_folder(self):
        path = self._open_file_dialog(is_dir=True)
        if path:
            self.setup_mod_dir = path
            dpg.set_value("setup_mod_path_display", path)

    def _execute_first_time_setup(self):
        dpg.configure_item("btn_import_setup", show=False)
        dpg.configure_item("setup_btn_game", show=False)
        dpg.configure_item("setup_btn_mod", show=False)
        dpg.set_value("setup_status", "                         Initializing transfer sequence...")
        dpg.configure_item("setup_status", color=[200, 200, 200])
        dpg.configure_item("setup_progress_group", show=True)
        threading.Thread(target=self._setup_thread_task, daemon=True).start()

    def _setup_thread_task(self):
        try:
            if not os.path.exists(SETUP_IMPORT_JSON):
                dpg.set_value("setup_status", f"ERROR: Missing {SETUP_IMPORT_JSON}")
                dpg.configure_item("setup_status", color=[255,50,50])
                return

            with open(SETUP_IMPORT_JSON, "r") as f:
                raw_data = json.load(f)
                
            lines = raw_data if isinstance(raw_data, list) else list(raw_data.values())[0]

            total = len(lines)
            if total == 0:
                dpg.set_value("setup_status", "Import file is empty.")
                return

            base_game_dst = os.path.join(DATA_DIR, "graphics_basegame")
            os.makedirs(base_game_dst, exist_ok=True)

            for i, line in enumerate(lines):
                clean_path = line.replace("\\", "/")
                if clean_path.startswith("/"): clean_path = clean_path[1:]
                if clean_path.startswith("graphics/"): clean_path = clean_path[9:]

                src = os.path.join(self.setup_game_dir, "starsector-core", "graphics", clean_path)
                dst = os.path.join(base_game_dst, clean_path)

                if os.path.exists(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                
                prog = (i + 1) / total
                dpg.set_value("setup_progress_bar", prog)
                dpg.configure_item("setup_progress_bar", overlay=f"Extracting Assets... {int(prog*100)}%")

            dpg.set_value("setup_status", "                      Transfer complete. Awaiting User Input...")
            dpg.configure_item("setup_status", color=[0, 255, 0])
            dpg.configure_item("btn_finalize_setup", show=True)
            
        except Exception as e:
            dpg.set_value("setup_status", f"Fatal Setup Error: {e}")
            dpg.configure_item("setup_status", color=[255, 50, 50])

    def _finalize_first_time_setup(self):
        self.state["mod_path"] = self.setup_mod_dir
        self.state["preferred_root"] = "graphics_basegame"
        self.needs_setup = False
        self.save_tool_state()
        
        dpg.configure_item("setup_modal", show=False)
        dpg.configure_item("Main", show=True)
        
        self.scan_virtual_filesystem()
        self.populate_file_list()
        
        if dpg.does_item_exist("preferred_root_combo"):
            dpg.configure_item("preferred_root_combo", items=self.available_roots)
            dpg.set_value("preferred_root_combo", "graphics_basegame")
        if dpg.does_item_exist("path_display"):
            dpg.set_value("path_display", self.setup_mod_dir)
        if dpg.does_item_exist("settings_game_path_display"):
            dpg.set_value("settings_game_path_display", self.setup_game_dir)
        
        self.load_live_preview_backgrounds()    
        self.refresh_live_preview()

    # --- MAIN SETUP ---
    def setup_gui(self):
        dpg.create_context()
        
        with dpg.theme(tag="rec_file_theme"):
            with dpg.theme_component(dpg.mvButton): 
                dpg.add_theme_color(dpg.mvThemeCol_Text, [0, 255, 0, 255], tag="rec_file_theme_color")

        with dpg.handler_registry():
            dpg.add_mouse_click_handler(callback=self.on_global_click)
            dpg.add_mouse_wheel_handler(callback=self.on_mouse_wheel)

        with dpg.texture_registry(tag="main_texture_registry", show=False):
            dpg.add_static_texture(width=1, height=1, default_value=[0,0,0,0], tag="static_void_texture")
            dpg.add_dynamic_texture(width=1, height=1, default_value=[0,0,0,0], tag="preview_texture_dynamic")
            dpg.add_dynamic_texture(width=1, height=1, default_value=[0.0, 0.0, 0.0, 0.0], tag="import_preview_tex")
            self.load_flag_textures()
            
            setup_logo_path = os.path.join(STAR_UI_DIR, "Star_UI_Glow.png")
            if os.path.exists(setup_logo_path):
                try:
                    w, h, c, d = dpg.load_image(setup_logo_path)
                    dpg.add_static_texture(width=w, height=h, default_value=d, tag="setup_logo_img")
                except: pass

            setup_wordart_path = os.path.join(STAR_UI_DIR, "Star_UI_Text.png")
            if os.path.exists(setup_wordart_path):
                try:
                    ww, wh, wc, wd = dpg.load_image(setup_wordart_path)
                    dpg.add_static_texture(width=ww, height=wh, default_value=wd, tag="setup_wordart_tex")
                except: pass

        initial_theme_name = self.state.get("app_theme", "Starsector (Default)")
        self.apply_theme(None, initial_theme_name, None)
        
        with dpg.theme() as self.selected_file_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Button, [0, 120, 215, 255])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [20, 140, 235, 255])

        tex_adj = self.state.get("texture_global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})
        col_adj = self.state.get("global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})

        with dpg.window(label="Adjust All", show=False, tag="adjust_all_window", width=250, height=210, autosize=False, 
                        no_collapse=True, no_resize=True, no_move=True, no_title_bar=True):
            dpg.add_text("Color Shift All Textures", color=[100, 255, 200])
            dpg.add_text("Only applies to this page", color=[150,150,150])
            dpg.add_separator()
            dpg.add_slider_float(label="Hue", tag="adj_all_h", min_value=-0.5, max_value=0.5, default_value=tex_adj["h"], callback=self.update_texture_globals)
            dpg.add_slider_float(label="Sat", tag="adj_all_s", min_value=-0.5, max_value=0.5, default_value=tex_adj["s"], callback=self.update_texture_globals)
            dpg.add_slider_float(label="Val", tag="adj_all_v", min_value=-0.5, max_value=0.5, default_value=tex_adj["v"], callback=self.update_texture_globals)
            dpg.add_spacer(height=10)
            dpg.add_button(label="RESET", callback=self.reset_texture_globals, width=-1)
            dpg.add_button(label="DONE", callback=self.close_adjust_all_window, width=-1)

        with dpg.window(label="Adjust All", show=False, tag="global_window", width=250, height=210, autosize=False, 
                        no_collapse=True, no_resize=True, no_move=True, no_title_bar=True):
            dpg.add_text("Shift All UI Colors", color=[100, 255, 200])
            dpg.add_text("Only applies to this page", color=[150,150,150])
            dpg.add_separator()
            dpg.add_slider_float(label="Hue", min_value=-0.1, max_value=0.1, tag="global_h", default_value=col_adj["h"], callback=self.apply_global_shift)
            dpg.add_slider_float(label="Sat", min_value=-0.5, max_value=0.5, tag="global_s", default_value=col_adj["s"], callback=self.apply_global_shift)
            dpg.add_slider_float(label="Val", min_value=-0.5, max_value=0.5, tag="global_v", default_value=col_adj["v"], callback=self.apply_global_shift)
            dpg.add_spacer(height=10)
            dpg.add_button(label="RESET", width=-1, callback=self.reset_global_changes)
            dpg.add_button(label="DONE", width=-1, callback=self.close_global_window)

        with dpg.window(label="STAR UI SETTINGS", show=False, modal=True, tag="settings_window", width=650, height=650, no_collapse=True, pos=(100, 100)):
            dpg.add_spacer(height=10)
            dpg.add_text("      Configure Applications Mod Export Folder, Default Textures, and Theme", color=[255,255,255])
            dpg.add_spacer(height=10)
            dpg.add_separator()
            dpg.add_spacer(height=10)
            dpg.add_text("Select Your [Starsector/mods] Folder | Or Desired Mod Export Folder:", color=[100, 255, 200])
            with dpg.group(horizontal=True):
                dpg.add_input_text(default_value=self.state['mod_path'], tag="path_display", width=400, readonly=True)
                dpg.add_button(label="Browse...", callback=self.select_mod_folder)
            dpg.add_spacer(height=20)
            dpg.add_separator()
            dpg.add_spacer(height=10)
            dpg.add_text("Select Your Prefered Tripad Editor Textures:", color=[100, 255, 200])
            dpg.add_text("Determines the default textures for the Preview, Editor, and Export...", color=[128,128,128])
            self.scan_virtual_filesystem()
            dpg.add_combo(items=self.available_roots, default_value=self.state.get("preferred_root", "graphics"), width=300, callback=self.set_preferred_root, tag="preferred_root_combo")             
            dpg.add_spacer(height=20)
            dpg.add_separator()
            dpg.add_spacer(height=10)
            dpg.add_text("Star UI Theme:", color=[100, 255, 200])
            with dpg.group(horizontal=True):              
                dpg.add_checkbox(label="- UI Frame Borders", default_value=self.state.get("show_borders", True), callback=self.toggle_borders)
            dpg.add_combo(items=list(self.themes.keys()), default_value=initial_theme_name, width=300, callback=self.apply_theme)    
            dpg.add_spacer(height=20)
            dpg.add_separator()
            dpg.add_spacer(height=10)          
            dpg.add_text("Dev Tools", color=[255, 100, 100])
            with dpg.group(horizontal=True):
                dpg.add_button(label="Style Editor", width=140, callback=lambda: dpg.show_style_editor())
                dpg.add_button(label="Metrics", width=140, callback=lambda: dpg.show_metrics())
                dpg.add_button(label="Debug", width=140, callback=lambda: dpg.show_debug())
            with dpg.group(horizontal=True):
                dpg.add_button(label="Font Manager", width=140, callback=lambda: dpg.show_font_manager())
                dpg.add_button(label="Item Registry", width=140, callback=lambda: dpg.show_item_registry())
                dpg.add_button(label="Documentation", width=140, callback=lambda: dpg.show_documentation())
                dpg.add_button(label="About", width=140, callback=lambda: dpg.show_about())
            dpg.add_text("Attention:\nThe application can be reset to default by deleting the 'Star_UI_Settings.json' in ~\n[Star_UI/Star_UI_Settings.json]", color=[128, 128, 128])
            dpg.add_spacer(height=20)
            dpg.add_button(label="CLOSE", width=-1, height=40, callback=lambda: dpg.configure_item("settings_window", show=False))

        with dpg.window(label="Restore?", show=False, tag="confirm_modal", width=250, height=100, autosize=False,
                        no_title_bar=True, no_resize=True, no_move=True):
            dpg.add_text("   Restore Default UI Colors?", color=[255, 100, 100])
            dpg.add_separator()
            dpg.add_button(label="RESTORE", width=-1, callback=self.restore_defaults)
            dpg.add_button(label="CANCEL", width=-1, callback=lambda: dpg.configure_item("confirm_modal", show=False))

        with dpg.window(label="Restore Tex?", show=False, tag="restore_all_tex_confirm", width=250, height=145, autosize=False,
                        no_title_bar=True, no_resize=True, no_move=True):
            dpg.add_text("     Restore All Textures?", color=[255, 100, 100])
            dpg.add_text("Textures will also be reset to \nusers preferred library", color=[128, 128, 128])
            dpg.add_separator()
            dpg.add_button(label="RESTORE", width=-1, callback=self.restore_all_textures)
            dpg.add_button(label="CANCEL", width=-1, callback=lambda: dpg.configure_item("restore_all_tex_confirm", show=False))
            
        with dpg.window(label="Apply All?", show=False, tag="apply_all_confirm", width=250, height=125, autosize=False,
                        no_title_bar=True, no_resize=True, no_move=True):
            dpg.add_text("    Apply these Values to ALL?", color=[255, 100, 100])
            dpg.add_text("Values will be applied \nto ALL textures", color=[128, 128, 128])
            dpg.add_separator()
            dpg.add_button(label="CONFIRM APPLY", width=-1, callback=self.apply_current_to_all)
            dpg.add_button(label="CANCEL", width=-1, callback=lambda: dpg.configure_item("apply_all_confirm", show=False))
            
        with dpg.window(label="Reset Factions?", show=False, tag="restore_factions_confirm", width=250, height=100, autosize=False,
                        no_title_bar=True, no_resize=True, no_move=True):
            dpg.add_text("  Restore Factions to Default?", color=[255, 100, 100])
            dpg.add_separator()
            dpg.add_button(label="RESTORE", width=-1, callback=self.restore_factions_defaults)
            dpg.add_button(label="CANCEL", width=-1, callback=lambda: dpg.configure_item("restore_factions_confirm", show=False))

        with dpg.window(tag="shared_color_editor", show=False, width=340, height=470, autosize=False, 
                        no_title_bar=True, no_resize=True, no_move=True):
            dpg.add_text("EDITING: Key", tag="shared_editor_title", color=[100, 255, 200])
            dpg.add_separator()
            dpg.add_color_picker(tag="shared_color_picker", callback=self.color_cb, no_side_preview=True, alpha_bar=True, width=310)
            dpg.add_text("Description:", color=[100, 255, 200])
            dpg.add_text("...", tag="shared_editor_desc", wrap=310)
            dpg.add_spacer(height=5)
            dpg.add_button(label="DONE", width=-1, callback=lambda: dpg.configure_item("shared_color_editor", show=False))

        # --- SETUP MODAL ---
        with dpg.window(tag="setup_modal", show=False, modal=True, no_title_bar=True, no_close=True, no_move=True, no_resize=True, width=700, height=570):
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=265)
                with dpg.group():
                    if dpg.does_alias_exist("setup_logo_img"):
                        dpg.add_image("setup_logo_img", width=150, height=150)
                    
                    if dpg.does_alias_exist("setup_wordart_tex"):
                        dpg.add_spacer(height=5)
                        dpg.add_image("setup_wordart_tex", width=150, height=35)
                    else:
                        with dpg.group(horizontal=True):
                            dpg.add_spacer(width=60)
                            dpg.add_text("STAR UI", color=[100, 200, 255])
            
            dpg.add_spacer(height=10)
            dpg.add_text("                     Welcome Commander! Please complete the initial setup.", color=[200, 200, 200])
            dpg.add_text("                              These settings can be changed later", color=[120, 120, 120])
            dpg.add_separator()
            dpg.add_spacer(height=10)
            
            dpg.add_text("Locate Starsector Game Directory:", color=[100, 255, 200])
            with dpg.group(horizontal=True):
                dpg.add_input_text(tag="setup_game_path_display", width=500, readonly=True, hint="e.g. C:/Program Files (x86)/Fractal Softworks/Starsector")
                dpg.add_button(label="Browse", tag="setup_btn_game", callback=self.select_setup_game_folder)
            
            dpg.add_spacer(height=10)
            dpg.add_text("Locate Mod Export Directory:", color=[100, 255, 200])
            with dpg.group(horizontal=True):
                dpg.add_input_text(tag="setup_mod_path_display", width=500, readonly=True, hint="Select the 'mods' folder inside your game directory")
                dpg.add_button(label="Browse", tag="setup_btn_mod", callback=self.select_setup_mod_folder)

            dpg.add_spacer(height=20)
            dpg.add_text("                                         Awaiting Input...", tag="setup_status", color=[150, 150, 150])
            dpg.add_spacer(height=10)
            
            with dpg.group(tag="setup_progress_group", show=False):
                dpg.add_progress_bar(tag="setup_progress_bar", default_value=0.0, width=-1, overlay="0%")
            
            dpg.add_spacer(height=20)
            dpg.add_button(label="IMPORT ASSETS", tag="btn_import_setup", width=-1, height=45, show=False, callback=self._execute_first_time_setup)
            dpg.bind_item_theme("btn_import_setup", "rec_file_theme")
            
            dpg.add_button(label="COMPLETE SETUP", tag="btn_finalize_setup", width=-1, height=45, show=False, callback=self._finalize_first_time_setup)
            dpg.bind_item_theme("btn_finalize_setup", "rec_file_theme")

        # --- Top Header / Command Bar ---
        with dpg.window(tag="Main", no_title_bar=True, no_move=True, no_resize=True, no_collapse=True, no_bring_to_front_on_focus=True):
            with dpg.group(horizontal=True):
                with dpg.group():
                    dpg.add_text("STAR UI v4.0", color=[100, 200, 255])
                    dpg.add_text("By DatBoi302", color=[100, 100, 100])
                    
                dpg.add_spacer(width=20)
                dpg.add_button(label="SETTINGS", width=100, height=45, callback=self.open_settings)
                dpg.add_spacer(width=50)
                dpg.add_button(label="IMPORT MOD", tag="btn_import_mod", width=140, height=45, callback=self.import_mod_wizard, user_data="zip")
                with dpg.tooltip("btn_import_mod"):
                    dpg.add_text("L-Click: Import .zip\nR-Click: Import Folder")
                with dpg.item_handler_registry(tag="import_handler"):
                    dpg.add_item_clicked_handler(button=dpg.mvMouseButton_Right, callback=self.import_mod_wizard, user_data="folder")
                dpg.bind_item_handler_registry("btn_import_mod", "import_handler")
                dpg.add_spacer(width=20)   
                dpg.add_button(label="UI COLORS", width=140, height=45, callback=self.switch_view, user_data="config")
                dpg.add_button(label="FACTION COLORS", width=140, height=45, callback=self.switch_view, user_data="faction")
                dpg.add_button(label="TRIPAD EDITOR", width=140, height=45, callback=self.switch_view, user_data="texture")
                dpg.add_spacer(width=20)
                dpg.add_input_text(default_value="Welcome Commander...", tag="status_text", width=380, height=45, multiline=True, readonly=True)
                dpg.add_spacer(width=20)             
                with dpg.group(width=200):
                    dpg.add_input_text(tag="gen_mod_name", hint="Star UI", width=-1)
                    dpg.add_progress_bar(tag="export_progress", default_value=0.0, width=-1, overlay="0%")
                dpg.add_button(label="EXPORT MOD", width=160, height=45, callback=self.export_mod)

            dpg.add_separator()

            # --- UI Colors / Editor ---
            with dpg.group(tag="group_config_editor", show=True):
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Restore Defaults", callback=self.toggle_restore_modal)
                    dpg.add_spacer(width=50)                    
                    dpg.add_input_text(hint="Search...", width=250, callback=lambda s, a: self.filter_colors(s, a))
                    dpg.add_spacer(width=50)
                    dpg.add_button(label="Adjust All", callback=self.toggle_global_window)
                    dpg.add_spacer(width=50)
                    dpg.add_input_text(hint="Preset Name", tag="preset_name_input", width=170)
                    dpg.add_button(label="Save", callback=lambda: self.save_preset("config"))
                    dpg.add_combo(tag="preset_combo_config", items=[], width=150)
                    dpg.add_button(label="Load", callback=lambda: self.confirm_load_preset("config"))
                    self.refresh_preset_list("config")

                dpg.add_separator()

                with dpg.group(horizontal=True):
                    with dpg.child_window(tag="cfg_col_left", width=610, height=800, border=False):
                        with dpg.child_window(height=-1, border=True):
                            with dpg.table(header_row=True, borders_innerV=True, borders_outerH=True, policy=dpg.mvTable_SizingFixedFit):
                                dpg.add_table_column(label="   Harmonies", width_fixed=True, init_width_or_weight=110)
                                dpg.add_table_column(label="  Default", width_fixed=True, init_width_or_weight=80)
                                dpg.add_table_column(label="  Custom Color", width_fixed=True, init_width_or_weight=120)
                                dpg.add_table_column(label="  Key Name", width_stretch=True)
                            
                            for category, items in self.default_colors.items():
                                with dpg.collapsing_header(label=category, tag=f"header_{category}", default_open=True):
                                    with dpg.table(header_row=False, borders_innerV=True, row_background=True, policy=dpg.mvTable_SizingFixedFit):
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=110)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=10)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=40)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=10)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=120)
                                        dpg.add_table_column(width_stretch=True)

                                        for sk, def_val in items.items():
                                            with dpg.table_row(tag=f"row_{category}_{sk}"):
                                                current_val = self.state["current_colors"].get(category, {}).get(sk, def_val)
                                                comp, tri, ana = self.calculate_harmonies(current_val)
                                                with dpg.group(horizontal=True):
                                                    dpg.add_color_button(default_value=comp, width=30, height=20, tag=f"btn_comp_{category}_{sk}", callback=self.apply_inline_harmony, user_data=(category, sk, comp))
                                                    dpg.add_color_button(default_value=tri, width=30, height=20, tag=f"btn_tri_{category}_{sk}", callback=self.apply_inline_harmony, user_data=(category, sk, tri))
                                                    dpg.add_color_button(default_value=ana, width=30, height=20, tag=f"btn_ana_{category}_{sk}", callback=self.apply_inline_harmony, user_data=(category, sk, ana))
                                                dpg.add_spacer(width=10)
                                                dpg.add_color_button(default_value=def_val, width=40, height=20, callback=self.restore_single_default, user_data=(category, sk, def_val))
                                                dpg.add_spacer(width=10)
                                                dpg.add_color_button(default_value=current_val, tag=f"btn_picker_{category}_{sk}", width=120, height=20, 
                                                                     callback=self.open_color_editor, user_data=(category, sk))
                                                dpg.add_text(sk)
                                                if self.color_descriptions.get(sk):
                                                    with dpg.tooltip(dpg.last_item()): dpg.add_text(f"{self.color_descriptions[sk]}")

                    with dpg.child_window(tag="cfg_col_right", width=1200, height=800, border=True): 
                        dpg.add_text("UI COLOR PREVIEW - In game results may vary | Some colors overlay and mix.", color=[100,200,255])
                        dpg.add_separator()
                        
                        # --- Live Preview Controls ---
                        with dpg.group(horizontal=True):
                            btn_exp = dpg.add_button(label="Export Preview", callback=self.export_live_preview_png)
                            dpg.bind_item_theme(btn_exp, "rec_file_theme")
                            dpg.add_spacer(width=20)
                            dpg.add_button(label="Pop-out Window", callback=self.toggle_popout_preview)
                            dpg.add_spacer(width=20)
                            dpg.add_combo([], default_value=self.state.get("live_preview_bg", ""), tag="live_preview_bg", width=150, callback=self.save_bg_state)
                            dpg.add_spacer(width=10)
                            dpg.add_slider_float(label="Zoom", tag="live_preview_zoom", default_value=0.6, min_value=0.2, max_value=2.0, width=150, callback=self.refresh_live_preview)
                            dpg.add_spacer(width=10)
                            dpg.add_checkbox(label="Scroll Zoom", default_value=self.state.get("enable_scroll_zoom", True), callback=self.toggle_scroll_zoom)
                        
                        dpg.add_spacer(height=10)
                        
                        # --- Live Preview Container ---
                        with dpg.child_window(tag="live_preview_container", width=-1, height=800, border=True, horizontal_scrollbar=True):
                            with dpg.drawlist(width=1920, height=1080, tag="live_preview_drawlist"):
                                pass
                        
            # --- Faction Colors / Editor ---
            with dpg.group(tag="group_faction_editor", show=False):
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Restore Defaults", callback=self.toggle_restore_factions_modal)
                    dpg.add_spacer(width=50)
                    dpg.add_input_text(hint="Search...", width=250, callback=self.filter_factions)
                    dpg.add_spacer(width=50)
                    dpg.add_button(label="Enable All", callback=self.enable_all_factions)
                    dpg.add_spacer(width=5)
                    dpg.add_button(label="Disable All", callback=self.disable_all_factions)
                    dpg.add_spacer(width=5)
                    dpg.add_button(label="Select Default", callback=self.select_default_enabled_factions)
                    with dpg.tooltip(dpg.last_item()): dpg.add_text("Enables standard factions only")
                    dpg.add_spacer(width=50)
                    dpg.add_input_text(hint="Preset Name", tag="preset_name_fac", width=170)
                    dpg.add_button(label="Save", callback=lambda: self.save_preset("faction"))
                    dpg.add_combo(tag="preset_combo_faction", items=[], width=150)
                    dpg.add_button(label="Load", callback=lambda: self.confirm_load_preset("faction"))
                    self.refresh_preset_list("faction")

                dpg.add_separator()

                with dpg.group(horizontal=True):
                    with dpg.child_window(tag="fac_col_left", width=650, height=800, border=False):
                        with dpg.child_window(height=-1, border=True):
                            with dpg.table(header_row=True, borders_innerV=True, borders_outerH=True, policy=dpg.mvTable_SizingFixedFit):
                                dpg.add_table_column(label=" Enable", width_fixed=True, init_width_or_weight=50)
                                dpg.add_table_column(label=" Default", width_fixed=True, init_width_or_weight=62)
                                dpg.add_table_column(label="   Color Picker", width_fixed=True, init_width_or_weight=130)
                                dpg.add_table_column(label="  UI Element", width_stretch=True)

                            priority_order = [
                                "Player", "Independent", "Hegemony", "Sindrian Diktat", 
                                "Persean League", "Tritachyon", "Luddic Church", 
                                "Pirates", "Luddic Path", "Remnant"
                            ]
                            
                            all_factions = sorted(self.faction_info.keys())
                            sorted_factions = []
                            for p in priority_order:
                                if p in all_factions:
                                    sorted_factions.append(p)
                                    all_factions.remove(p)
                            sorted_factions.extend(all_factions)

                            for fname in sorted_factions:
                                f_info = self.faction_info[fname]
                                with dpg.collapsing_header(label=fname, default_open=True):
                                    with dpg.table(header_row=False, borders_innerV=True, row_background=True, policy=dpg.mvTable_SizingFixedFit):
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=8)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=26)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=12)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=40)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=12)
                                        dpg.add_table_column(width_fixed=True, init_width_or_weight=130)
                                        dpg.add_table_column(width_stretch=True)

                                        for key, def_val in f_info["colors"].items():
                                            with dpg.table_row(tag=f"row_fac_{fname}_{key}"):
                                                dpg.add_spacer(width=8)
                                                is_active = key in self.state["active_faction_keys"].get(fname, [])
                                                dpg.add_checkbox(default_value=is_active, callback=self.toggle_faction_key_active, user_data=(fname, key), tag=f"chk_fac_{fname}_{key}")
                                                with dpg.tooltip(dpg.last_item()):
                                                    dpg.add_text("Enable/Disable for Mod Export")
                                                dpg.add_spacer(width=12)
                                                dpg.add_color_button(default_value=def_val, width=40, height=20, callback=self.restore_single_faction_default, user_data=(fname, key, def_val))
                                                current_val = self.state["current_faction_colors"][fname].get(key, def_val)
                                                dpg.add_spacer(width=12)
                                                dpg.add_color_button(default_value=current_val, tag=f"btn_fac_{fname}_{key}", width=120, height=20, 
                                                                     callback=self.open_faction_color_editor, user_data=(fname, key))
                                                dpg.add_text(key)

                    with dpg.child_window(tag="fac_col_right", width=1200, height=800, border=True):
                        dpg.add_text("FACTION COLOR PREVIEW: Faction Color is represented by the border around their flag.", color=[100,200,255])
                        dpg.add_text("The 'Enabled' left side column matches the faction coloring settings that are enabled or disabled in the base game...", color=[128,128,128])
                        dpg.add_separator()
                        with dpg.drawlist(width=1000, height=800, tag="fac_preview_drawlist"):
                            pass
                        self.draw_faction_preview()

            # --- TRIPAD Editor ---
            with dpg.group(tag="group_texture_lab", show=False):
                if not HAS_IMG_LIBS:
                    dpg.add_text("ERROR: Graphics Libraries missing.", color=[255,0,0])
                else:
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="Restore Defaults", callback=self.toggle_restore_all_tex_modal)
                        dpg.add_spacer(width=50)
                        dpg.add_input_text(hint="Search...", width=250, callback=self.filter_textures)
                        dpg.add_spacer(width=50)
                        dpg.add_button(label="Adjust All", callback=self.toggle_adjust_all_window)
                        dpg.add_spacer(width=50)
                        dpg.add_input_text(hint="Preset Name", tag="preset_name_tex", width=170)
                        dpg.add_button(label="Save", callback=lambda: self.save_preset("texture"))
                        dpg.add_combo(tag="preset_combo_texture", items=[], width=150)
                        dpg.add_button(label="Load", callback=lambda: self.confirm_load_preset("texture"))
                        self.refresh_preset_list("texture")
                        dpg.add_spacer(width=30)
                        dpg.add_text("Copy/Paste Values:")
                        for i in range(5):
                            dpg.add_button(label=f"{i+1}", tag=f"slot_btn_{i}", width=40, height=20, callback=self.slot_load_click, user_data=i)
                            with dpg.item_handler_registry(tag=f"slot_handler_{i}"):
                                dpg.add_item_clicked_handler(button=dpg.mvMouseButton_Right, callback=self.slot_save_click, user_data=i)
                            dpg.bind_item_handler_registry(f"slot_btn_{i}", f"slot_handler_{i}")
                            with dpg.tooltip(f"slot_btn_{i}"): dpg.add_text("L-Click: Paste to Texture\nR-Click: Copy Values to Slot")

                    dpg.add_separator()

                    with dpg.group(horizontal=True):
                        with dpg.child_window(tag="tex_col_left", width=300, height=900, border=True):
                            dpg.add_text("          UI Textures Library", color=[100,200,255])
                            dpg.add_text("  [!] - Denotes important UI textures", color=[128,128,128])
                            dpg.add_separator()
                            with dpg.group(tag="file_list_group"):
                                self.populate_file_list()
                            dpg.add_button(label="Refresh", callback=lambda: self.populate_file_list(), width=-1)
                        
                        with dpg.child_window(tag="tex_col_right", width=-1, height=900, border=True):
                            with dpg.group(horizontal=True):
                                with dpg.child_window(width=280, border=False):
                                    dpg.add_text("Preview Control", color=[100,200,255])
                                    dpg.add_slider_float(label="Zoom", tag="preview_zoom", default_value=1.0, min_value=0.1, max_value=10.0, callback=self.refresh_texture_preview)
                                    dpg.add_separator()
                                    dpg.add_text("Adjustments", color=[100,200,255])
                                    dpg.add_slider_float(label="Hue", tag="tex_h", min_value=-0.5, max_value=0.5, default_value=0, callback=self.refresh_texture_preview)
                                    dpg.add_slider_float(label="Sat", tag="tex_s", min_value=0.0, max_value=2.0, default_value=1, callback=self.refresh_texture_preview)
                                    dpg.add_slider_float(label="Val", tag="tex_v", min_value=0.0, max_value=2.0, default_value=1, callback=self.refresh_texture_preview)
                                    dpg.add_slider_float(label="Contrast", tag="tex_contrast", min_value=0.0, max_value=3.0, default_value=1.0, callback=self.refresh_texture_preview)
                                    dpg.add_slider_float(label="Gamma", tag="tex_gamma", min_value=0.0, max_value=3.0, default_value=1.0, callback=self.refresh_texture_preview)
                                    dpg.add_slider_float(label="Alpha", tag="tex_a", min_value=0.0, max_value=1.0, default_value=1, callback=self.refresh_texture_preview)                                   
                                    dpg.add_spacer(height=10)
                                    dpg.add_separator()                                    
                                    dpg.add_text("Extra FX", color=[100,200,255])
                                    dpg.add_slider_float(label="Noise", tag="tex_noise", min_value=0.0, max_value=1.0, default_value=0.0, callback=self.refresh_texture_preview)
                                    dpg.add_slider_float(label="Scanlines", tag="tex_scanlines", min_value=0.0, max_value=1.0, default_value=0.0, callback=self.refresh_texture_preview)
                                    dpg.add_checkbox(label="Grayscale", tag="filter_grayscale", callback=self.refresh_texture_preview)
                                    dpg.add_checkbox(label="Invert Colors", tag="filter_invert", callback=self.refresh_texture_preview)
                                    dpg.add_checkbox(label="Find Edges", tag="filter_edges", callback=self.refresh_texture_preview)                                                                       
                                    dpg.add_spacer(height=10)
                                    dpg.add_separator()                                 
                                    dpg.add_text("Recolor", color=[100,200,255])
                                    with dpg.group(width=-1):
                                        dpg.add_checkbox(label="Enable", tag="tex_tint_enabled", callback=self.refresh_texture_preview)
                                        dpg.add_color_edit(label="Color Select", tag="tex_tint_picker", default_value=[255,255,255,255], 
                                                             callback=self.refresh_texture_preview,
                                                             no_inputs=True, width=150, no_picker=False, alpha_bar=True)
                                    dpg.add_spacer(height=15)
                                    
                                    with dpg.group(width=-1):                                       
                                        dpg.add_text("Chroma Key", color=[100,200,255])
                                        dpg.add_checkbox(label="Enable", tag="chroma_enabled", callback=self.refresh_texture_preview)
                                        with dpg.group(horizontal=True):
                                            dpg.add_color_edit(label="Target", tag="chroma_target", no_inputs=True, width=120, callback=self.refresh_texture_preview, alpha_bar=True)
                                            dpg.add_text("    >    ") 
                                            dpg.add_color_edit(label="Replace", tag="chroma_replace", no_inputs=True, width=120, callback=self.refresh_texture_preview, alpha_bar=True)
                                        dpg.add_slider_float(label="Tol", tag="chroma_tol", min_value=1.0, max_value=200.0, default_value=50.0, callback=self.refresh_texture_preview)
                                                                              
                                    dpg.add_separator()
                                    dpg.add_spacer(height=15)
                                    dpg.add_button(label="Reset Current Texture", callback=self.reset_current_texture, width=-1)
                                    dpg.add_spacer(height=15)
                                    dpg.add_button(label="Apply Values to All Textures", callback=self.toggle_apply_all_confirm_modal, width=-1)

                                with dpg.child_window(border=True, width=1295, height=898):
                                    with dpg.group(horizontal=True):
                                        dpg.add_text("No Image Selected", tag="preview_label")
                                        dpg.add_spacer(width=15)
                                        dpg.add_text("Source: [None]", tag="source_label_display", color=[255, 200, 100])
                                    
                                    with dpg.group(tag="source_selector_group", show=False):
                                        dpg.add_spacer(height=5)
                                        with dpg.group(horizontal=True):
                                            dpg.add_button(label=" < ", callback=self.cycle_source_root, user_data=-1)
                                            dpg.add_button(label=" > ", callback=self.cycle_source_root, user_data=1)
                                            dpg.add_spacer(width=20)
                                            dpg.add_checkbox(tag="source_active_checkbox", callback=self.set_active_export_source)
                                            dpg.add_spacer(width=10)
                                            dpg.add_text("Use This Texture when Exporting Mod", color=[100, 255, 200])
                                        dpg.add_separator()
                                        dpg.add_spacer(height=5)

                                    with dpg.group(tag="preview_container_group"):
                                        dpg.add_image("preview_texture_dynamic", tag="preview_image_item", width=100, height=100)

        user32 = ctypes.windll.user32
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        w = max(1600, int(sw * 0.8))
        h = int(sh * 0.8)
        x = int((sw - w) / 2)
        y = int((sh - h) / 2)
        dpg.create_viewport(title="Star UI", width=w, height=h, x_pos=x, y_pos=y, decorated=True)
        
        icon_path_root = ICON_FILENAME
        icon_path_sub = os.path.join(STAR_UI_DIR, ICON_FILENAME)
        final_icon_path = None
        
        if os.path.exists(icon_path_root):
            final_icon_path = icon_path_root
        elif os.path.exists(icon_path_sub):
            final_icon_path = icon_path_sub
            
        if final_icon_path:
            dpg.set_viewport_small_icon(final_icon_path)
            dpg.set_viewport_large_icon(final_icon_path)

        dpg.set_viewport_resize_callback(self.resize_windows)
        
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.maximize_viewport() 
        
        dpg.set_primary_window("Main", True)
        
        if getattr(self, 'needs_setup', False) and not self.DEV_SKIP_SETUP:
            dpg.configure_item("setup_modal", show=True)
            def center_setup_modal():
                if dpg.does_item_exist("setup_modal"):
                    vp_cw = dpg.get_viewport_client_width()
                    vp_ch = dpg.get_viewport_client_height()
                    dpg.set_item_pos("setup_modal", [(vp_cw - 700) // 2, (vp_ch - 515) // 2])
            dpg.set_frame_callback(5, callback=center_setup_modal)
        else:
            self.load_live_preview_backgrounds()
            self.refresh_live_preview() 
        
        dpg.start_dearpygui()
        dpg.destroy_context()
    
    def get_fac_color(self, fname, key):
        return self.state["current_faction_colors"].get(fname, {}).get(key, [255, 255, 255, 255])

    def draw_faction_preview(self):
        if not dpg.does_item_exist("fac_preview_drawlist"): return
        dpg.delete_item("fac_preview_drawlist", children_only=True)
        p_base = self.get_fac_color("Player", "baseUIColor")
        p_dark = self.get_fac_color("Player", "darkUIColor")
        p_grid = self.get_fac_color("Player", "gridUIColor")
        p_col  = self.get_fac_color("Player", "color")
        p_bright = self.get_fac_color("Player", "brightUIColor")
        p_sec  = self.get_fac_color("Player", "secondaryUIColor")
        dpg.draw_rectangle((10, 10), (990, 300), fill=p_dark, thickness=0, parent="fac_preview_drawlist")
        for i in range(20, 990, 50): dpg.draw_line((i, 10), (i, 300), color=p_grid, thickness=1, parent="fac_preview_drawlist")
        for i in range(20, 300, 50): dpg.draw_line((10, i), (990, i), color=p_grid, thickness=1, parent="fac_preview_drawlist")
        dpg.draw_rectangle((10, 10), (990, 300), color=p_base, thickness=2, parent="fac_preview_drawlist")
        dpg.draw_rectangle((20, 20), (300, 60), fill=(0,0,0,100), color=p_base, thickness=1, parent="fac_preview_drawlist")
        dpg.draw_text((30, 30), "FLEET COMMAND", size=20, color=p_col, parent="fac_preview_drawlist")
        dpg.draw_text((20, 80), "Flux Capacitors:", size=15, color=p_col, parent="fac_preview_drawlist")
        dpg.draw_rectangle((150, 80), (400, 95), fill=(50,50,50,255), thickness=0, parent="fac_preview_drawlist")
        dpg.draw_rectangle((150, 80), (350, 95), fill=p_bright, thickness=0, parent="fac_preview_drawlist")
        dpg.draw_text((20, 110), "Secondary Sys:", size=15, color=p_sec, parent="fac_preview_drawlist")
        dpg.draw_rectangle((150, 110), (400, 125), fill=(50,50,50,255), thickness=0, parent="fac_preview_drawlist")
        dpg.draw_rectangle((150, 110), (280, 125), fill=p_sec, thickness=0, parent="fac_preview_drawlist")
        dpg.draw_circle((800, 150), 80, color=p_base, thickness=2, parent="fac_preview_drawlist")
        dpg.draw_circle((800, 150), 75, color=p_bright, thickness=1, parent="fac_preview_drawlist")
        dpg.draw_text((760, 140), "TARGET", size=18, color=p_bright, parent="fac_preview_drawlist")

        start_y = 340
        start_x = 20
        flag_w, flag_h = 192, 120
        padding = 20
        row1 = ["Independent", "Hegemony", "Sindrian Diktat", "Persean League"]
        row2 = ["Tritachyon", "Luddic Church", "Pirates", "Luddic Path"]
        def draw_flag_row(factions, y_pos):
            x = start_x
            for fac in factions:
                f_col = self.get_fac_color(fac, "color")
                if not f_col: f_col = [255, 255, 255, 255]
                dpg.draw_rectangle((x, y_pos), (x+flag_w+10, y_pos+flag_h+10), color=f_col, thickness=3, parent="fac_preview_drawlist")
                if fac in self.loaded_flags:
                    f_data = self.loaded_flags[fac]
                    dpg.draw_image(f_data["tag"], (x+5, y_pos+5), (x+5+flag_w, y_pos+5+flag_h), uv_min=f_data.get("uv_min", (0,0)), uv_max=f_data.get("uv_max", (1,1)), parent="fac_preview_drawlist")
                else: dpg.draw_text((x+10, y_pos+30), "Missing", size=14, parent="fac_preview_drawlist")
                dpg.draw_text((x, y_pos + flag_h + 15), fac, size=14, color=f_col, parent="fac_preview_drawlist")
                x += flag_w + 10 + padding
        draw_flag_row(row1, start_y)
        draw_flag_row(row2, start_y + flag_h + 50)

    def save_preset(self, mode):
        folder = CONFIG_PRESETS_DIR
        tag = "preset_name_input"
        data = {}
        if mode == "config":
            tag = "preset_name_input"
            folder = CONFIG_PRESETS_DIR
            data = {"__version__": "1.0", "colors": self.state["current_colors"], "__global_adjustments__": self.state.get("global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})}
        elif mode == "faction":
            tag = "preset_name_fac"
            folder = FACTION_PRESETS_DIR
            data = {"__version__": "1.0", "colors": self.state["current_faction_colors"], "active": self.state["active_faction_keys"]}
        else:
            tag = "preset_name_tex"
            folder = HUD_PRESETS_DIR
            for rel_path in self.virtual_file_map:
                active_root = self.get_active_root_for_file(rel_path)
                if not active_root: continue
                key = f"{active_root}/{rel_path}"
                if key in self.texture_settings: data[key] = copy.deepcopy(self.texture_settings[key])
            data["__texture_global_adjustments__"] = self.state.get("texture_global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})
            data["__active_roots_override"] = copy.deepcopy(self.active_roots)
        name = dpg.get_value(tag)
        if not name: return
        filepath = os.path.join(folder, f"{name}.json")
        self.save_json_pretty(filepath, data)
        self.refresh_preset_list(mode)
        self._set_status(f"{mode.capitalize()} Preset Saved!", [0, 255, 0])

    def confirm_load_preset(self, mode):
        folder = CONFIG_PRESETS_DIR
        tag = "preset_combo_config"
        if mode == "config": tag, folder = "preset_combo_config", CONFIG_PRESETS_DIR
        elif mode == "faction": tag, folder = "preset_combo_faction", FACTION_PRESETS_DIR
        else: tag, folder = "preset_combo_texture", HUD_PRESETS_DIR
        name = dpg.get_value(tag)
        if not name: return
        filepath = os.path.join(folder, f"{name}.json")
        if os.path.exists(filepath):
            with open(filepath, 'r') as f: loaded_data = json.load(f)
            if mode == "config":
                if "colors" in loaded_data:
                    colors_data = loaded_data["colors"]
                    self.state["global_adjustments"] = loaded_data.get("__global_adjustments__", {"h": 0.0, "s": 0.0, "v": 0.0})
                else: colors_data = loaded_data
                for cat, items in self.default_colors.items():
                    if cat in colors_data:
                        for key in items:
                            if key in colors_data[cat]: self.state["current_colors"][cat][key] = colors_data[cat][key]
                self._initialize_snapshot()
                self.update_ui_from_state()
            elif mode == "faction":
                if "colors" in loaded_data and "active" in loaded_data:
                    self.state["current_faction_colors"] = loaded_data["colors"]
                    self.state["active_faction_keys"] = loaded_data["active"]
                    self.update_faction_ui_from_state()
            else:
                if "__texture_global_adjustments__" in loaded_data: self.state["texture_global_adjustments"] = loaded_data.pop("__texture_global_adjustments__")
                if "__active_roots_override" in loaded_data: self.active_roots.update(loaded_data.pop("__active_roots_override"))
                self.texture_settings.update(loaded_data) 
                if self.current_virtual_path: self.load_texture_to_lab(self.current_virtual_path)
            self.save_tool_state()
            self._set_status(f"{mode.capitalize()} Loaded.", [0, 255, 0])

    def refresh_preset_list(self, mode):
        if mode == "config": folder, tag = CONFIG_PRESETS_DIR, "preset_combo_config"
        elif mode == "faction": folder, tag = FACTION_PRESETS_DIR, "preset_combo_faction"
        else: folder, tag = HUD_PRESETS_DIR, "preset_combo_texture"
        presets = [f.replace(".json", "") for f in os.listdir(folder) if f.endswith(".json")]
        dpg.configure_item(tag, items=presets)

    def update_faction_ui_from_state(self):
        for fname, data in self.faction_info.items():
            active_keys = self.state["active_faction_keys"].get(fname, [])
            colors = self.state["current_faction_colors"].get(fname, {})
            for key, def_val in data["colors"].items():
                chk_tag = f"chk_fac_{fname}_{key}"
                if dpg.does_item_exist(chk_tag): dpg.set_value(chk_tag, key in active_keys)
                pk_tag = f"btn_fac_{fname}_{key}"
                if dpg.does_item_exist(pk_tag): dpg.configure_item(pk_tag, default_value=colors.get(key, def_val))

    def restore_single_faction_default(self, sender, app_data, user_data):
        fname, key, def_val = user_data
        self.state["current_faction_colors"][fname][key] = def_val
        self.save_tool_state()
        if dpg.does_item_exist(f"btn_fac_{fname}_{key}"): dpg.configure_item(f"btn_fac_{fname}_{key}", default_value=def_val)

    def restore_factions_defaults(self, sender=None, app_data=None):
        for fname, data in self.faction_info.items():
            self.state["current_faction_colors"][fname] = copy.deepcopy(data["colors"])
            self.state["active_faction_keys"][fname] = copy.deepcopy(data["active"])
        self.save_tool_state()
        self.update_faction_ui_from_state()
        if dpg.does_item_exist("restore_factions_confirm"):
            dpg.configure_item("restore_factions_confirm", show=False)
            self.active_anchor_window = None
        self._set_status("All Factions Reset to Defaults.", [0, 255, 0])

    def enable_all_factions(self, sender, app_data):
        for fname, data in self.faction_info.items(): self.state["active_faction_keys"][fname] = list(data["colors"].keys())
        self.save_tool_state()
        self.update_faction_ui_from_state()

    def disable_all_factions(self, sender, app_data):
        for fname in self.faction_info.keys(): self.state["active_faction_keys"][fname] = []
        self.save_tool_state()
        self.update_faction_ui_from_state()

    def select_default_enabled_factions(self, sender, app_data):
        for fname, data in self.faction_info.items(): self.state["active_faction_keys"][fname] = copy.deepcopy(data.get("active", []))
        self.save_tool_state()
        self.update_faction_ui_from_state()
        self._set_status("Faction Selection Reset to Defaults.", [255, 200, 0])

    def select_settings_game_folder(self):
        path = self._open_file_dialog(is_dir=True)
        if path:
            self.state["game_path"] = path
            if dpg.does_item_exist("settings_game_path_display"):
                dpg.set_value("settings_game_path_display", path)
            self.save_tool_state()

    def select_mod_folder(self):
        path = self._open_file_dialog(is_dir=True)
        if path:
            self.state["mod_path"] = path
            if dpg.does_item_exist("path_display"): dpg.set_value("path_display", path)
            self.save_tool_state()

    def export_mod(self):
        path = self.state["mod_path"]
        if not path or not os.path.exists(path):
            self._set_status("ERROR: Invalid Mod Path!", color=[255,0,0])
            return
        custom_name = dpg.get_value("gen_mod_name")
        if custom_name: custom_name = "".join([c for c in custom_name if c.isalnum() or c in (' ', '_', '-')]).strip()
        mod_display_name = custom_name if custom_name else "Star UI"
        mod_folder_name = custom_name.replace(" ", "_") if custom_name else "Star UI"
        
        try:
            mod_root = os.path.join(path, mod_folder_name)
            config_path = os.path.join(mod_root, "data", "config")
            graphics_path = os.path.join(mod_root, "graphics")
            factions_path = os.path.join(mod_root, "data", "world", "factions")
            os.makedirs(config_path, exist_ok=True)
            os.makedirs(graphics_path, exist_ok=True)
            os.makedirs(factions_path, exist_ok=True)
            
            with open(os.path.join(mod_root, "mod_info.json"), 'w') as f:
                json.dump({
                    "id": mod_folder_name.lower(), "name": mod_display_name, "author": "DatBoi302", 
                    "version": "4.0", "gameVersion": "0.98a-RC8", "description": f"Custom Starsector UI made using Star UI. ({mod_display_name})"
                }, f, indent=4)
            
            final_json_structure = {}
            design_type_group = {}
            for category in self.state["current_colors"]:
                if category == "Design Types":
                    for key, val in self.state["current_colors"][category].items(): design_type_group[key] = val
                elif category != "Factions":
                    for key, val in self.state["current_colors"][category].items(): final_json_structure[key] = val
            if design_type_group: final_json_structure["designTypeColors"] = design_type_group
            self.save_json_pretty(os.path.join(config_path, "settings.json"), final_json_structure)

            faction_export_count = 0
            for fname, fdata in self.faction_info.items():
                active_keys = self.state["active_faction_keys"].get(fname, [])
                if not active_keys: continue
                faction_json = {}
                current_values = self.state["current_faction_colors"].get(fname, {})
                for key in active_keys:
                    val = current_values.get(key)
                    if val: faction_json[key] = val
                if faction_json:
                    out_file = os.path.join(factions_path, fdata["file"])
                    self.save_json_pretty(out_file, faction_json)
                    faction_export_count += 1

            if HAS_IMG_LIBS:
                processed_count = 0
                file_list = []
                for rel_path in self.virtual_file_map.keys():
                    active_root = self.get_active_root_for_file(rel_path)
                    if not active_root: continue
                    file_list.append((rel_path, active_root))
                
                total_files = len(file_list)
                if dpg.does_item_exist("export_progress"):
                    dpg.set_value("export_progress", 0.0)
                    dpg.configure_item("export_progress", overlay="0%")

                for i, (rel_path, active_root) in enumerate(file_list):
                    if total_files > 0 and dpg.does_item_exist("export_progress"):
                        prog = (i / total_files)
                        dpg.set_value("export_progress", prog)
                        dpg.configure_item("export_progress", overlay=f"{int(prog*100)}%")

                    setting_key = f"{active_root}/{rel_path}"
                    settings = self.texture_settings.get(setting_key, {})
                    src_path = os.path.join(DATA_DIR, active_root, rel_path)
                    if not os.path.exists(src_path): continue
                        
                    try:
                        img = Image.open(src_path).convert("RGBA")
                        if settings.get("filter_grayscale", False): img = ImageEnhance.Color(img).enhance(0.0)
                        if settings.get("filter_invert", False):
                            r, g, b, a = img.split()
                            img = Image.merge("RGBA", (ImageOps.invert(r), ImageOps.invert(g), ImageOps.invert(b), a))
                        if settings.get("filter_edges", False):
                            r, g, b, a = img.split()
                            rgb = Image.merge("RGB", (r,g,b)).filter(ImageFilter.FIND_EDGES)
                            r, g, b = rgb.split()
                            img = Image.merge("RGBA", (r,g,b,a))

                        g = self.state.get("texture_global_adjustments", {"h":0,"s":0,"v":0})
                        s_val = max(0.0, settings.get("s", 1.0) + g["s"])
                        v_val = max(0.0, settings.get("v", 1.0) + g["v"])
                        h_val = settings.get("h", 0.0) + g["h"]
                        c_val = settings.get("contrast", 1.0)
                        gamma_val = settings.get("gamma", 1.0)
                        
                        if s_val != 1.0: img = ImageEnhance.Color(img).enhance(s_val)
                        if v_val != 1.0: img = ImageEnhance.Brightness(img).enhance(v_val)
                        if c_val != 1.0: img = ImageEnhance.Contrast(img).enhance(c_val)
                        if gamma_val != 1.0 and gamma_val > 0.01:
                            inv_gamma = 1.0 / gamma_val
                            table = [int(((i / 255.0) ** inv_gamma) * 255) for i in range(256)]
                            r, g, b, a = img.split()
                            r = r.point(table)
                            g = g.point(table)
                            b = b.point(table)
                            img = Image.merge("RGBA", (r, g, b, a))
                        if h_val != 0.0:
                            img_hsv = img.convert("HSV")
                            h, s, v = img_hsv.split()
                            np_h = np.array(h, dtype=int)
                            shift_amt = int(h_val * 255)
                            np_h = (np_h + shift_amt) % 255
                            h_new = Image.fromarray(np_h.astype('uint8'), 'L')
                            img_hsv = Image.merge("HSV", (h_new, s, v))
                            r, g, b = img_hsv.convert("RGB").split()
                            a = img.split()[3]
                            img = Image.merge("RGBA", (r, g, b, a))
                        if settings.get("a", 1.0) != 1.0:
                            r, g, b, a = img.split()
                            np_a = np.array(a, dtype=float) * settings["a"]
                            np_a = np.clip(np_a, 0, 255).astype('uint8')
                            img = Image.merge("RGBA", (r, g, b, Image.fromarray(np_a, 'L')))
                        if settings.get("chroma_enabled", False):
                            target = settings.get("chroma_target", [0, 255, 0, 255])
                            replace = settings.get("chroma_replace", [0, 0, 0, 0])
                            tol = settings.get("chroma_tol", 50.0)
                            arr = np.array(img)
                            t_rgb = np.array(target[:3])
                            diff = arr[:, :, :3] - t_rgb
                            dist = np.linalg.norm(diff, axis=2)
                            mask = dist < tol
                            arr[mask] = replace
                            img = Image.fromarray(arr)
                        if settings.get("tint_enabled", False):
                            tint_color = settings.get("tint_color", [255, 255, 255, 255])
                            if tint_color[:3] != [255, 255, 255]:
                                 tr, tg, tb = tint_color[0]/255.0, tint_color[1]/255.0, tint_color[2]/255.0
                                 arr = np.array(img).astype(float)
                                 arr[:, :, 0] *= tr
                                 arr[:, :, 1] *= tg
                                 arr[:, :, 2] *= tb
                                 img = Image.fromarray(arr.astype('uint8'))
                                 
                        arr = np.array(img)
                        alpha_mask = arr[:, :, 3] > 0
                        noise_amt = settings.get("noise", 0.0)
                        scan_strength = settings.get("scanlines", 0.0)
                        if noise_amt > 0.0:
                            strength = int(noise_amt * 100)
                            noise = np.random.randint(-strength, strength + 1, arr[:, :, :3].shape)
                            rgb = arr[:, :, :3].astype(int)
                            rgb[alpha_mask] += noise[alpha_mask]
                            np.clip(rgb, 0, 255, out=rgb)
                            arr[:, :, :3] = rgb.astype('uint8')
                        if scan_strength > 0.0:
                            mult = np.ones(arr.shape[:2], dtype=float)
                            mult[::2, :] = 1.0 - scan_strength
                            rgb = arr[:, :, :3].astype(float)
                            rgb *= mult[:, :, np.newaxis]
                            arr[:, :, :3] = rgb.astype('uint8')
                        img = Image.fromarray(arr)
                        
                        dest_path = os.path.join(graphics_path, rel_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        img.save(dest_path)
                        processed_count += 1
                        
                    except Exception as ex: pass

                if dpg.does_item_exist("export_progress"):
                    dpg.set_value("export_progress", 1.0)
                    dpg.configure_item("export_progress", overlay="100%")

            self._set_status(f"Mod Generated: {mod_folder_name} ({faction_export_count} factions, {processed_count} textures)", [0, 255, 0])
        except Exception as e:
            self._set_status(f"Error: {str(e)}", [255, 0, 0])

    def _set_status(self, text, color=[200, 200, 200]):
        if dpg.does_item_exist("status_text"):
            dpg.set_value("status_text", text)
            dpg.configure_item("status_text", default_value=text)

    def restore_single_default(self, sender, app_data, user_data):
        cat, sk, def_val = user_data
        self._update_color_state(cat, sk, def_val)

    def apply_inline_harmony(self, sender, app_data, user_data):
        cat, sk, new_rgba = user_data
        self._update_color_state(cat, sk, new_rgba)

    def color_cb(self, sender, app_data, user_data):
        cat, sk = user_data
        new_val = [int(round(x * 255)) for x in app_data]
        self._update_color_state(cat, sk, new_val)

    def _update_color_state(self, cat, sk, new_val):
        self.state["current_colors"][cat][sk] = new_val
        vals = self.state.get("global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})
        h_shift, s_shift, v_shift = vals["h"], vals["s"], vals["v"]
        if self.snapshot_colors:
             r, g, b = new_val[0]/255.0, new_val[1]/255.0, new_val[2]/255.0
             h, s, v = colorsys.rgb_to_hsv(r, g, b)
             h = (h - h_shift) % 1.0
             s = max(0.0, min(1.0, s - s_shift))
             v = max(0.0, min(1.0, v - v_shift))
             nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
             self.snapshot_colors[cat][sk] = [int(nr*255), int(ng*255), int(nb*255), new_val[3]]
             
        self.save_tool_state()
        
        btn_tag = f"btn_picker_{cat}_{sk}"
        if dpg.does_item_exist(btn_tag):
            dpg.configure_item(btn_tag, default_value=new_val)
            
        self.update_preview_element(sk, new_val)
        self.update_row_harmonies(cat, sk, new_val)
        
        if self.popout_process and self.popout_process.is_alive():
            current_time = time.time()
            if not hasattr(self, "_last_color_ipc") or (current_time - getattr(self, "_last_color_ipc", 0)) > 0.033:
                flat_colors = {}
                for c_cat, items in self.state["current_colors"].items():
                    for k, v in items.items():
                        flat_colors[k] = v
                self.popout_queue.put({"type": "state", "colors": flat_colors})
                self._last_color_ipc = current_time

    def update_ui_from_state(self):
        for cat, items in self.state["current_colors"].items():
            for sk, sv in items.items():
                btn_tag = f"btn_picker_{cat}_{sk}"
                if dpg.does_item_exist(btn_tag): dpg.configure_item(btn_tag, default_value=sv)
                self.update_preview_element(sk, sv)
                self.update_row_harmonies(cat, sk, sv)

    def restore_defaults(self, sender=None, app_data=None, user_data=None):
        self.state["current_colors"] = json.loads(json.dumps(self.default_colors))
        self.state["global_adjustments"] = {"h": 0.0, "s": 0.0, "v": 0.0}
        
        if dpg.does_item_exist("global_h"): dpg.set_value("global_h", 0.0)
        if dpg.does_item_exist("global_s"): dpg.set_value("global_s", 0.0)
        if dpg.does_item_exist("global_v"): dpg.set_value("global_v", 0.0)
            
        self._initialize_snapshot()
        self.update_ui_from_state()
        self.save_tool_state()
        
        if dpg.does_item_exist("confirm_modal"):
            dpg.configure_item("confirm_modal", show=False)
            self.active_anchor_window = None
            
        self._set_status("Restored to Vanilla Defaults.", [255, 210, 0])

    def open_global_window(self):
        vals = self.state.get("global_adjustments", {"h": 0.0, "s": 0.0, "v": 0.0})
        dpg.set_value("global_h", vals["h"])
        dpg.set_value("global_s", vals["s"])
        dpg.set_value("global_v", vals["v"])
        dpg.configure_item("global_window", show=True)

    def apply_global_shift(self, sender, app_data, user_data):
        if not self.snapshot_colors: return
        h_shift = dpg.get_value("global_h")
        s_shift = dpg.get_value("global_s")
        v_shift = dpg.get_value("global_v")
        self.state["global_adjustments"] = {"h": h_shift, "s": s_shift, "v": v_shift}
        for cat, items in self.snapshot_colors.items():
            for sk, rgba in items.items():
                r, g, b = rgba[0]/255.0, rgba[1]/255.0, rgba[2]/255.0
                h, s, v = colorsys.rgb_to_hsv(r, g, b)
                h = (h + h_shift) % 1.0
                s = max(0.0, min(1.0, s + s_shift))
                v = max(0.0, min(1.0, v + v_shift))
                nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
                new_rgba = [int(nr*255), int(ng*255), int(nb*255), rgba[3]]
                self.state["current_colors"][cat][sk] = new_rgba
        self.save_tool_state()
        self.update_ui_from_state()

    def reset_global_changes(self):
        if self.snapshot_colors:
            self.state["current_colors"] = copy.deepcopy(self.snapshot_colors)
            self.update_ui_from_state()
            dpg.set_value("global_h", 0.0)
            dpg.set_value("global_s", 0.0)
            dpg.set_value("global_v", 0.0)
            self.state["global_adjustments"] = {"h": 0.0, "s": 0.0, "v": 0.0}
        self._set_status("Global Adjustments Reset...", [255, 210, 0])

    def close_global_window(self):
        self.save_tool_state()
        dpg.configure_item("global_window", show=False)

    def calculate_harmonies(self, current_rgba):
        r, g, b = current_rgba[0]/255.0, current_rgba[1]/255.0, current_rgba[2]/255.0
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        alpha = current_rgba[3]
        def make_col(hue_shift):
            nh = (h + hue_shift) % 1.0
            nr, ng, nb = colorsys.hsv_to_rgb(nh, s, v)
            return [int(nr*255), int(ng*255), int(nb*255), alpha]
        return make_col(0.5), make_col(1/3.0), make_col(1/12.0)

    def update_row_harmonies(self, cat, sk, current_rgba):
        comp, tri, ana = self.calculate_harmonies(current_rgba)
        if dpg.does_item_exist(f"btn_comp_{cat}_{sk}"): dpg.configure_item(f"btn_comp_{cat}_{sk}", default_value=comp, user_data=(cat, sk, comp))
        if dpg.does_item_exist(f"btn_tri_{cat}_{sk}"): dpg.configure_item(f"btn_tri_{cat}_{sk}", default_value=tri, user_data=(cat, sk, tri))
        if dpg.does_item_exist(f"btn_ana_{cat}_{sk}"): dpg.configure_item(f"btn_ana_{cat}_{sk}", default_value=ana, user_data=(cat, sk, ana))

    def open_settings(self, sender=None, app_data=None):
        self.scan_virtual_filesystem()
        if dpg.does_item_exist("preferred_root_combo"):
            dpg.configure_item("preferred_root_combo", items=self.available_roots)
            dpg.set_value("preferred_root_combo", self.state.get("preferred_root", "graphics"))
        if dpg.does_item_exist("path_display"):
            dpg.set_value("path_display", self.state.get("mod_path", ""))
        if dpg.does_item_exist("settings_game_path_display"):
            dpg.set_value("settings_game_path_display", self.state.get("game_path", ""))
        dpg.configure_item("settings_window", show=True)

    def toggle_borders(self, sender, app_data, user_data):
        self.state["show_borders"] = app_data
        self.save_tool_state()
        self.apply_theme(None, self.state.get("app_theme", "Starsector (Default)"), None)

    def apply_theme(self, sender, app_data, user_data):
        theme_name = app_data
        if theme_name not in self.themes: return
        t_data = self.themes[theme_name]
        merged_styles = copy.deepcopy(DEFAULT_STYLES)
        for s_key in THEME_STYLE_MAP:
            if s_key in t_data: merged_styles[s_key] = t_data[s_key]
        if self.state.get("show_borders", True):
            merged_styles["FrameBorderSize"] = 1
        else:
            merged_styles["FrameBorderSize"] = 0

        with dpg.theme() as new_theme:
            with dpg.theme_component(dpg.mvAll):
                for key, val in t_data.items():
                    if key in THEME_COLOR_MAP:
                        c_val = list(val)
                        if len(c_val) == 3: c_val.append(255)
                        dpg.add_theme_color(THEME_COLOR_MAP[key], c_val)
                for s_name, s_id in THEME_STYLE_MAP.items():
                    if s_name in merged_styles:
                        val = merged_styles[s_name]
                        if isinstance(val, (list, tuple)):
                            if len(val) >= 2: dpg.add_theme_style(s_id, val[0], val[1])
                            else: dpg.add_theme_style(s_id, val[0])
                        else:
                            dpg.add_theme_style(s_id, val)
        dpg.bind_theme(new_theme)
        
        hl_color = t_data.get("HighlightColor", [0, 255, 0, 255])
        hl_color = list(hl_color)
        if len(hl_color) == 3: hl_color.append(255) 
            
        if dpg.does_item_exist("rec_file_theme_color"):
            dpg.set_value("rec_file_theme_color", hl_color)
            
        self.state["app_theme"] = theme_name
        self.save_tool_state()

    def get_color(self, key):
        for cat, items in self.state["current_colors"].items():
            if key in items: return items[key]
        return [255, 255, 255, 255]

    def register_preview(self, key, tag, prop):
        if key not in self.preview_tags: self.preview_tags[key] = []
        self.preview_tags[key].append({"tag": tag, "prop": prop})

    def update_preview_element(self, key, new_rgba):
        if key in self.preview_tags:
            for tag_info in self.preview_tags[key]:
                tag = tag_info["tag"]
                prop = tag_info["prop"] 
                if dpg.does_item_exist(tag):
                    if prop == "fill":
                        dpg.configure_item(tag, fill=new_rgba)
                    else:
                        dpg.configure_item(tag, color=new_rgba)

    def filter_colors(self, sender, filter_string):
        f = filter_string.lower()
        for cat, items in self.default_colors.items():
            header_tag = f"header_{cat}"
            cat_visible = False
            for sk in items.keys():
                row_tag = f"row_{cat}_{sk}"
                visible = f in sk.lower() or f in cat.lower()
                if visible:
                    dpg.configure_item(row_tag, show=True)
                    cat_visible = True
                else:
                    dpg.configure_item(row_tag, show=False)
            dpg.configure_item(header_tag, show=cat_visible)
            
    def filter_factions(self, sender, filter_string):
        f = filter_string.lower()
        for fname, data in self.faction_info.items():
            header_tag = f"header_fac_{fname}"
            faction_match = f in fname.lower()      
            any_row_visible = False
            
            for key in data["colors"].keys():
                row_tag = f"row_fac_{fname}_{key}"
                if not dpg.does_item_exist(row_tag): continue
                key_match = f in key.lower()
                
                if faction_match or key_match:
                    dpg.configure_item(row_tag, show=True)
                    any_row_visible = True
                else:
                    dpg.configure_item(row_tag, show=False)

            if dpg.does_item_exist(header_tag):
                dpg.configure_item(header_tag, show=any_row_visible)

    def import_mod_wizard(self, sender, app_data, user_data=None):
        mode = user_data if user_data else "zip"
        self.import_staging = {"name": "", "settings_path": None, "textures": [], "has_settings": False, "root_prefix": ""}
        
        path = None
        if mode == "folder": path = self._open_file_dialog(is_dir=True)
        else: path = self._open_file_dialog(is_dir=False, filetypes=[("Mod Archive", "*.zip"), ("All Files", "*.*")])
        if not path: return

        is_zip = zipfile.is_zipfile(path) if mode != "folder" else False
        mod_name = "Imported Mod"
        mod_root = "" 
        
        try:
            if is_zip:
                with zipfile.ZipFile(path, 'r') as z:
                    nl = z.namelist()
                    found_info = None
                    for n in nl:
                        if n.endswith("mod_info.json") and "__MACOSX" not in n:
                            if found_info is None or len(n) < len(found_info):
                                found_info = n
                    if found_info:
                        mod_root = os.path.dirname(found_info)
                        try:
                            with z.open(found_info) as f:
                                data = json.load(f)
                                mod_name = data.get("name", "Imported Mod")
                        except: pass
                    if mod_root and not mod_root.endswith("/"): mod_root += "/"
                    self.import_staging["root_prefix"] = mod_root

                    for n in nl:
                        if "__MACOSX" in n: continue
                        if not n.startswith(mod_root): continue
                        rel_to_mod = n[len(mod_root):] 
                        if rel_to_mod == "data/config/settings.json":
                            self.import_staging["settings_path"] = n
                            self.import_staging["has_settings"] = True
                        if "graphics/" in rel_to_mod and n.lower().endswith(".png"):
                            idx = rel_to_mod.find("graphics/")
                            if idx != -1:
                                rel_clean = rel_to_mod[idx+9:]
                                if rel_clean: self.import_staging["textures"].append({"full": n, "rel": rel_clean, "checked": False})

            else:
                found_info_path = None
                for r, d, f in os.walk(path):
                    if "mod_info.json" in f:
                        found_info_path = os.path.join(r, "mod_info.json")
                        break
                real_root = path
                if found_info_path:
                    real_root = os.path.dirname(found_info_path)
                    try:
                        with open(found_info_path, 'r') as f:
                            data = json.load(f)
                            mod_name = data.get("name", "Imported Mod")
                    except: pass
                self.import_staging["root_prefix"] = real_root

                for r, d, f in os.walk(real_root):
                    for file in f:
                        full_p = os.path.join(r, file)
                        rel_to_mod = os.path.relpath(full_p, real_root).replace("\\", "/")
                        if rel_to_mod == "data/config/settings.json":
                            self.import_staging["settings_path"] = full_p
                            self.import_staging["has_settings"] = True
                        if "graphics/" in rel_to_mod and rel_to_mod.lower().endswith(".png"):
                            idx = rel_to_mod.find("graphics/")
                            if idx != -1:
                                rel_clean = rel_to_mod[idx+9:]
                                if rel_clean: self.import_staging["textures"].append({"full": full_p, "rel": rel_clean, "checked": False})

        except Exception as e:
            self._set_status(f"Import Analysis Failed: {e}", color=[255, 0, 0])
            return

        self.import_staging["name"] = mod_name
        self.import_staging["source"] = path
        self.import_staging["is_zip"] = is_zip
        
        recommended = []
        if os.path.exists(RECOMMENDED_IMPORT_FILE):
            try:
                with open(RECOMMENDED_IMPORT_FILE, 'r') as f:
                    rec_data = json.load(f)
                    recommended = rec_data.get("Recommended_Import", [])
            except: pass
            
        for t in self.import_staging["textures"]:
            if t["rel"] in recommended:
                t["checked"] = True

        if dpg.does_item_exist("import_modal"): dpg.delete_item("import_modal")
        
        vp_w = dpg.get_viewport_width()
        vp_h = dpg.get_viewport_height()
        m_w, m_h = 1200, 800
        pos_x = (vp_w - m_w) // 2
        pos_y = (vp_h - m_h) // 2
        
        with dpg.window(label="Import UI Mod", tag="import_modal", modal=True, width=m_w, height=m_h, pos=(pos_x, pos_y)):
            dpg.add_text(f"Importing: {mod_name}", color=[100, 255, 200])
            dpg.add_separator()                     
            if self.import_staging["has_settings"]:
                dpg.add_checkbox(label="Would you like to Save this Mod as a Preset?", default_value=True, tag="import_settings_check")
            else:
                dpg.add_text("No settings.json found.", color=[255,200,0])
            dpg.add_input_text(label="Preset Name", default_value=mod_name, tag="import_name_input")    
            
            dpg.add_separator()
            
            with dpg.group(horizontal=True):
                dpg.add_button(label="Select All", width=150, callback=self._import_sel_all)
                dpg.add_spacer(width=15)
                dpg.add_button(label="Select Recommended", width=150, callback=self._import_sel_rec, user_data=recommended)              
                dpg.add_spacer(width=15)
                dpg.add_button(label="Select None", width=150, callback=self._import_sel_none)                

            dpg.add_spacer(height=5)
            
            with dpg.group(horizontal=True):
                with dpg.group(width=725):
                    dpg.add_text(f"Found {len(self.import_staging['textures'])} Textures")
                    dpg.add_input_text(hint="Filter files...", callback=self._import_filter_list, width=-1)
                    
                    with dpg.child_window(height=560, border=True):
                        with dpg.table(header_row=True, tag="import_table", policy=dpg.mvTable_SizingFixedFit, scrollY=True):
                            dpg.add_table_column(label="Imp", width_fixed=True, init_width_or_weight=30)
                            dpg.add_table_column(label="File (Click to Preview)", width_stretch=True)
                            
                            for i, t in enumerate(self.import_staging["textures"]):
                                with dpg.table_row(tag=f"import_row_{i}"):
                                    dpg.add_checkbox(default_value=t["checked"], tag=f"import_chk_{i}", user_data=i)
                                    dpg.add_selectable(label=t["rel"], tag=f"import_sel_{i}", callback=self._preview_import_texture, user_data=i)

                with dpg.child_window(width=440, height=610, border=True):
                    dpg.add_text("Preview", color=[150,150,150])
                    dpg.add_separator()
                    dpg.add_image("import_preview_tex", tag="import_preview_img_item", width=380, height=380)

            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_button(label="CANCEL", width=100, callback=lambda: dpg.delete_item("import_modal"))
                dpg.add_spacer(width=15)
                btn_exec = dpg.add_button(label="IMPORT MOD", width=200, callback=self._execute_import)
                dpg.bind_item_theme(btn_exec, "rec_file_theme")

    def _preview_import_texture(self, sender, app_data, user_data):
        idx = user_data
        for i in range(len(self.import_staging["textures"])):
            if i != idx:
                tag = f"import_sel_{i}"
                if dpg.does_item_exist(tag): dpg.set_value(tag, False)
        dpg.set_value(sender, True)

        t = self.import_staging["textures"][idx]
        src = self.import_staging["source"]
        
        try:
            img = None
            if self.import_staging["is_zip"]:
                with zipfile.ZipFile(src, 'r') as z:
                    with z.open(t["full"]) as f:
                        data = f.read()
                        img = Image.open(io.BytesIO(data))
                        img.load()
            else:
                img = Image.open(t["full"])
                img.load()
                
            if img:
                img = img.convert("RGBA")
                padded_img, orig_w, orig_h, pad_w, pad_h, uv_min, uv_max = process_texture_for_opengl(img)

                d_list = (np.array(padded_img).astype(np.float32) / 255.0).flatten()
                
                if getattr(self, "import_tex_pad_w", 0) != pad_w or getattr(self, "import_tex_pad_h", 0) != pad_h:
                    if dpg.does_item_exist("import_preview_img_item"):
                         dpg.configure_item("import_preview_img_item", texture_tag="static_void_texture")
                    dpg.delete_item("import_preview_tex")
                    dpg.add_dynamic_texture(width=pad_w, height=pad_h, default_value=d_list, tag="import_preview_tex", parent="main_texture_registry")
                    self.import_tex_w = orig_w
                    self.import_tex_h = orig_h
                    self.import_tex_pad_w = pad_w
                    self.import_tex_pad_h = pad_h
                else:
                    dpg.set_value("import_preview_tex", d_list)
                    
                display_w, display_h = orig_w, orig_h
                max_dim = 380
                if orig_w > max_dim or orig_h > max_dim:
                    ratio = min(max_dim/orig_w, max_dim/orig_h)
                    display_w = int(orig_w * ratio)
                    display_h = int(orig_h * ratio)
                
                dpg.configure_item("import_preview_img_item", width=display_w, height=display_h, uv_min=uv_min, uv_max=uv_max, texture_tag="import_preview_tex")
        except: pass

    def _import_sel_all(self):
        for i in range(len(self.import_staging["textures"])):
            if dpg.does_item_exist(f"import_chk_{i}"): dpg.set_value(f"import_chk_{i}", True)
            
    def _import_sel_none(self):
        for i in range(len(self.import_staging["textures"])):
            if dpg.does_item_exist(f"import_chk_{i}"): dpg.set_value(f"import_chk_{i}", False)

    def _import_sel_rec(self, s, a, recommended):
        for i, t in enumerate(self.import_staging["textures"]):
            val = t["rel"] in recommended
            if dpg.does_item_exist(f"import_chk_{i}"): dpg.set_value(f"import_chk_{i}", val)

    def _import_filter_list(self, s, filter_txt):
        f = filter_txt.lower()
        for i, t in enumerate(self.import_staging["textures"]):
            show = f in t["rel"].lower()
            dpg.configure_item(f"import_row_{i}", show=show)

    def _execute_import(self):
        mod_name_raw = dpg.get_value("import_name_input")
        if not mod_name_raw: mod_name_raw = "Imported_Mod"
        
        sanitized_suffix = re.sub(r'[^a-z]', '', mod_name_raw.lower())
        if not sanitized_suffix: sanitized_suffix = "imported"
            
        new_root_name = f"graphics_{sanitized_suffix}"
        new_root_path = os.path.join(DATA_DIR, new_root_name)
        
        do_settings = dpg.get_value("import_settings_check") if dpg.does_item_exist("import_settings_check") else False
        
        selected_indices = []
        for i in range(len(self.import_staging["textures"])):
            if dpg.get_value(f"import_chk_{i}"):
                selected_indices.append(i)
        
        if not selected_indices and not do_settings:
            dpg.delete_item("import_modal")
            return

        if selected_indices: os.makedirs(new_root_path, exist_ok=True)
        
        imported_count = 0
        src = self.import_staging["source"]
        is_zip = self.import_staging["is_zip"]
        
        if selected_indices:
            try:
                if is_zip:
                    with zipfile.ZipFile(src, 'r') as z:
                        for idx in selected_indices:
                            t = self.import_staging["textures"][idx]
                            dest = os.path.join(new_root_path, t["rel"])
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            with z.open(t["full"]) as zf, open(dest, 'wb') as df:
                                shutil.copyfileobj(zf, df)
                            imported_count += 1
                else:
                    for idx in selected_indices:
                        t = self.import_staging["textures"][idx]
                        dest = os.path.join(new_root_path, t["rel"])
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.copy2(t["full"], dest)
                        imported_count += 1
            except Exception as e:
                self._set_status(f"Copy Failed: {e}", [255, 0, 0])
                return

        if do_settings and self.import_staging["has_settings"]:
            try:
                content = ""
                if is_zip:
                    with zipfile.ZipFile(src, 'r') as z:
                        with z.open(self.import_staging["settings_path"]) as f:
                            content = f.read().decode('utf-8')
                else:
                    with open(self.import_staging["settings_path"], 'r') as f:
                        content = f.read()

                content = re.sub(r'//.*', '', content)
                content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
                content = re.sub(r',(\s*[}\]])', r'\1', content)
                mod_set_data = json.loads(content)
                final_preset_struct = {} 
                for cat, items in self.default_colors.items():
                    final_preset_struct[cat] = {}
                    for k, v in items.items():
                        if k in mod_set_data:
                            val = mod_set_data[k]
                            if isinstance(val, list) and len(val) == 4:
                                final_preset_struct[cat][k] = val
                            else: final_preset_struct[cat][k] = v
                        else:
                            final_preset_struct[cat][k] = v
                
                p_name = "".join([c for c in mod_name_raw if c.isalnum() or c in (' ', '_', '-')]).strip()
                p_path = os.path.join(CONFIG_PRESETS_DIR, f"{p_name}.json")
                self.save_json_pretty(p_path, final_preset_struct)
            except Exception as e:
                self._set_status(f"Settings Import Error: {e}", [255, 0, 0])

        if selected_indices:
            tex_preset = {}
            roots_override = {}
            for idx in selected_indices:
                t = self.import_staging["textures"][idx]
                roots_override[t["rel"]] = new_root_name
                key = f"{new_root_name}/{t['rel']}"
                tex_preset[key] = {
                    "h": 0.0, "s": 1.0, "v": 1.0, "a": 1.0, 
                    "tint_color": [255, 255, 255, 255]
                }
            tex_preset["__active_roots_override"] = roots_override
            p_name = "".join([c for c in mod_name_raw if c.isalnum() or c in (' ', '_', '-')]).strip()
            tp_path = os.path.join(HUD_PRESETS_DIR, f"{p_name}.json")
            self.save_json_pretty(tp_path, tex_preset)

        dpg.delete_item("import_modal")
        self.populate_file_list()
        self.refresh_preset_list("config")
        self.refresh_preset_list("texture")
        self._set_status(f"Imported {imported_count} textures to {new_root_name}.", [0, 255, 0])

if __name__ == "__main__":
    mp.freeze_support()
    StarUI()