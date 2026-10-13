-- Tag by Exposure: Plugins > Tag by Exposure (Lua) > Tag by Exposure > Tag this photo.

local function tag_this_photo()
    local stats = efas.statistics()
    if not stats then
        efas.notify("Open a photo first")
        return
    end
    local tags = {}
    if stats.mean < 80 then
        tags[#tags + 1] = "Exposure/Dark"
    elseif stats.mean > 170 then
        tags[#tags + 1] = "Exposure/Bright"
    else
        tags[#tags + 1] = "Exposure/Normal"
    end
    if stats.blown_pct > 1 then tags[#tags + 1] = "Exposure/Blown highlights" end
    efas.add_tags(tags)
    print("Tagged " .. efas.photo().name .. ": " .. table.concat(tags, ", "))
    efas.notify("Tagged: " .. table.concat(tags, ", "))
end

efas.add_menu_item{ label = "Tag this photo", submenu = "Tag by Exposure", on_click = tag_this_photo }
