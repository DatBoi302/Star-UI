
            --- Code Snippets ---
                Colors:
                Star UI Blue: , color=[100,200,255]
                Green-ish-aqua: , color=[100, 255, 200]
                White: , color=[255,255,255]
                Red: , color=[255,0,0]
                Grey: , color=[128,128,128]
                Yellow: , color=[255,200,0]

  
    
    
    
	Search - Preset
	            # --- UI Colors ---
            with dpg.group(tag="group_config_editor", show=True):
                with dpg.group(horizontal=True):
                    dpg.add_input_text(hint="Search...", width=250, callback=lambda s, a: self.filter_colors(s, a))
                    dpg.add_spacer(width=50)
                    dpg.add_button(label="Adjust All", callback=self.toggle_global_window)
                    dpg.add_button(label="Restore Defaults", callback=self.toggle_restore_modal)
                    dpg.add_spacer(width=50)
                    dpg.add_input_text(hint="Preset Name", tag="preset_name_input", width=170)
                    dpg.add_button(label="Save", callback=lambda: self.save_preset("config"))
                    dpg.add_combo(tag="preset_combo_config", items=[], width=150)
                    dpg.add_button(label="Load", callback=lambda: self.confirm_load_preset("config"))
                    self.refresh_preset_list("config")
                    
                    =================================================================
                    
                                # --- TRIPAD EDITOR Image Preview Container ---
                                with dpg.child_window(border=True, width=-1, height=-1):
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
                                            dpg.add_checkbox(label="Use this Texture for Mod Export", tag="source_active_checkbox", callback=self.set_active_export_source)                                       
                                        dpg.add_separator()
                                        dpg.add_spacer(height=5)

                                    with dpg.group(tag="preview_container_group"):
                                        dpg.add_image("preview_texture_dynamic", tag="preview_image_item", width=150, height=150)





tex_right_w = w - 280 - 40  # Calculates width for the right side
tex_h = h - 175             # Calculates height for the Tripad editor






# Added max_width parameter with a default
    def load_flag_textures(self, max_width=256):
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
                    
                    # --- CHANGE IS HERE ---
                    # Use the variable instead of the hardcoded 128
                    if w > max_width:
                        ratio = max_width / w
                        img = img.resize((max_width, int(h*ratio)), Image.LANCZOS)
                        w, h = img.size
                    # ----------------------

                    data_list = np.array(img).astype(np.float32) / 255.0
                    flat_data = data_list.flatten().tolist()
                    
                    tag = f"flag_tex_{fac_name}"
                    
                    # CRITICAL NOTE: If you are resizing dynamically (runtime), 
                    # you must delete the old texture first.
                    if dpg.does_item_exist(tag):
                        dpg.delete_item(tag)

                    dpg.add_static_texture(width=w, height=h, default_value=flat_data, tag=tag, parent="main_texture_registry")
                    self.loaded_flags[fac_name] = {"tag": tag, "w": w, "h": h}
                    
                except Exception as e:
                    print(f"Failed to load flag {fname}: {e}")


                            sorted_factions.extend(all_factions)

                            for fname in sorted_factions:
                                f_info = self.faction_info[fname]
                                with dpg.collapsing_header(label=fname, default_open=True, tag=f"header_fac_{fname}"):
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
                                                    
                                                    
 Import Mod / Columns / Final Check on Functions / Possible Changes to Preview / Folder Structure !!!! CHECK FACTION STUFF IN UI COLORs Tab
 
How would I make this vertical?

                                    with dpg.group(horizontal=True):
                                        dpg.add_checkbox(tag="tex_tint_enabled", callback=self.refresh_texture_preview)
                                        dpg.add_color_edit(tag="tex_tint_picker", default_value=[255,255,255,255], 
                                                             callback=self.refresh_texture_preview,
                                                             no_inputs=True, width=150, no_picker=False, alpha_bar=True)
                                    dpg.add_spacer(height=15)

Enable recommended in Faction Editor                                    
TRIPAD EDITOR send status message when global slider reset



        with dpg.window(label="Import UI Mod", tag="import_modal", modal=True, width=800, height=550, pos=(200, 100)):
            dpg.add_text(f"Importing: {mod_name}", color=[100, 255, 200])
            dpg.add_separator()
            dpg.add_input_text(label="Preset Name", default_value=mod_name, tag="import_name_input")
            
            if self.import_staging["has_settings"]:
                dpg.add_checkbox(label="Would you like to Save this Mod as a Preset?", default_value=True, tag="import_settings_check")
            else:
                dpg.add_text("No settings.json found.", color=[255,200,0])
            
            dpg.add_separator()
  

How would I shrink the coloumn rows heights?  