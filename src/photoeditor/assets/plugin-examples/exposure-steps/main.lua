-- Exposure Steps: nudge the exposure by a third of a stop with a button.
-- efas.set_edit changes the edit exactly as the sliders do, so each press is one undoable history step.

local STEP = 1 / 3

local module = efas.add_module{ title = "Exposure steps", tab = "exposure" }   -- in the WB Correction tab
local reading = module:add_label{ text = "Open a photo." }

local function show()
    local photo = efas.photo()
    if photo then
        reading:set_text(string.format("Exposure: %+.2f EV", photo.exposure_ev))
    else
        reading:set_text("Open a photo.")
    end
end

local function nudge(amount)
    local photo = efas.photo()
    if not photo then
        efas.notify("Open a photo first")
        return
    end
    efas.set_edit{ exposure_ev = photo.exposure_ev + amount }
    show()
end

module:add_button{ label = "Darker (-1/3 EV)", on_click = function() nudge(-STEP) end }
module:add_button{ label = "Brighter (+1/3 EV)", on_click = function() nudge(STEP) end }
module:add_button{ label = "Back to 0", on_click = function() efas.set_edit{ exposure_ev = 0 } show() end }

efas.on("photo_opened", show)    -- keep the reading right when another photo opens
efas.on("edit_changed", show)    -- ... and when the sliders move it
show()
