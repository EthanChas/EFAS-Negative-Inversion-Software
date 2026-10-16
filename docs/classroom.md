# Classroom

The **Classroom** (the view button between Maps and Workbench) is a built-in guide for new people, and a much fuller version of the **?** help on each tool: guides to the basics of photography, how film works and scanning, and then an in-depth guide to every tool in EFAS that explains what the tool does to the picture, what each control really changes, when to reach for it and what to watch out for. The guides are written to be read, in prose, not ticked off. They are in the order a beginner needs them, with a **search box**, and a **Show me** button that takes you to the tool a guide is about.

## The order of the course

1. **Start here**: what EFAS does, how to use the Classroom, the whole job in nine steps, a tour of the window.
2. **Photography basics**: light and exposure, the exposure triangle (aperture, shutter speed, ISO), stops and EV, reading a histogram, clipping, dynamic range and contrast, colour temperature and white balance, hue / saturation / lightness, focus and sharpness, RAW and bit depth, composition and cropping.
3. **How film works**: colour negative, black-and-white and slide film, why a negative is orange, film speed and grain, formats, exposure latitude, dust and scratches, handling and storage.
4. **Scanning your film**: the camera-scanning setup, the backlight, exposure and focus, keeping film flat and masked, shooting tethered, the scan quality check.
5. **Getting around EFAS**: opening photos, the Library, the Workbench, the filmstrip and culling, the histogram, viewing tools, how modules work, the order the modules act in, undo, History and Snapshots, Find.
6. **Convert, Frame & Clean, Tone, Color, Detail, Finish and export**: one guide per tool, tab by tab, in the order a picture is worked on. Each explains what the tool is for, how it works on the picture (the maths, in plain words), what every control does, when to use it and the mistakes to avoid.
7. **Working a whole roll**: the Roll Card, presets and copy / paste, virtual copies, tags and smart collections, Hotstack, slideshows, whole-roll tools, backups.
8. **Worked examples**: your first roll start to finish, removing a colour cast, uneven light, cleaning dust, black-and-white, slide film, a flat scan, one look on a whole roll, a tethered session.
9. **Reference**: the keyboard shortcuts (the table follows your own keybinds), a glossary, troubleshooting, the Settings page by page, Advanced mode, the command line.

## Using it

* **Search** looks in every guide's title, its keywords, its summary and its text; every word you type has to be in the guide, and the best matches come first (a title that has the words, then a keyword or the tool's name, then the text). It understands the same common words as Find (`brightness` finds Exposure). `Esc` clears it, `Enter` opens the first result.
* **Previous / Next** walk the guides in order. A guide's **Read next** list and the links in its text go to related guides.
* **Show me: *tool*** appears on a guide to one tool. It takes you to the editor (or the Workbench), opens that module and flashes it.
* **Where you were** is remembered: the Classroom opens on the guide you were last reading. There are no ticks or progress bars; read what you need, in any order.

## For developers

The writing is in `src/photoeditor/features/classroom`: `content_basics.py`, `content_app.py`, `content_convert.py`, `content_tone.py`, `content_finish.py` and `content_reference.py` hold the guides in a small mark-up (headings, bullet and numbered lists, Tip / Try / Note / Careful boxes, `**bold**`, `` `code` ``, `[[lesson-id]]` links, `@shortcuts`), `content.py` puts them in order, and `logic.py` parses, searches and renders them (no Qt). `desktop/view/classroom_view.py` is the page. `tests/test_classroom_logic.py` checks the course (every link goes somewhere, the sections are in order, every tool has a guide, and the tool guides are real explanations: a minimum length, headings, and not mostly lists); `tests/test_classroom.py` checks the page and that every guide's tool is a real module of the editor.
