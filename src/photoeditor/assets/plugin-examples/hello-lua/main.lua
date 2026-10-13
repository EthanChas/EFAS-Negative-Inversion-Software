-- Hello (Lua): a menu item, a module with a button, and some output.
-- Switch it on in Settings > Plugins, then look in the Plugins menu and the Plugins tab.

print("Hello from " .. efas.plugin_name .. " (EFAS " .. efas.version .. ")")   -- shows in View > Plugin Output

efas.add_menu_item{
    label = "Say hello",
    on_click = function()
        efas.message("Hello from Lua!")
    end,
}

local module = efas.add_module{ title = "Hello (Lua)" }          -- goes in the Plugins tab
local label = module:add_label{ text = "Press the button." }

local clicks = efas.settings_get("clicks", 0)                    -- saved between runs
if clicks > 0 then label:set_text("You have pressed it " .. clicks .. " times before.") end

module:add_button{
    label = "Click me",
    on_click = function()
        clicks = clicks + 1
        efas.settings_set("clicks", clicks)
        label:set_text("Pressed " .. clicks .. " times.")
        efas.notify("Hello button pressed")
    end,
}
