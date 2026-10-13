# Security and trust

A plugin is a program that runs inside EFAS. Treat installing one the way you treat installing any program: only use plugins from people you trust, and read what a plugin does if you can.

## What EFAS does for you

- **Every plugin starts switched off.** Putting a folder in the plugins folder does not run anything. You turn each plugin on yourself in Settings > Plugins, and the choice is remembered by the plugin's id.
- **Errors are contained.** A plugin that fails to load, or raises an error in a callback, is reported in the Plugin Output window and nothing else is affected.
- **Everything a plugin does is on the screen.** There is no background process: a plugin only runs inside EFAS, while EFAS is running, and stops when it is switched off.
- **Edits go through history.** `set_edit` makes ordinary history steps, so a plugin's changes to a photo can be undone.
- **EFAS never sends a plugin anywhere.** Nothing about plugins is uploaded; the program only goes online for the update check and the Film Colour Reference (see the main README's Privacy section).

## Lua plugins are sandboxed

A Lua plugin runs in a box:

| Can | Cannot |
|---|---|
| Use the Lua language and its string, table, math, utf8 and coroutine libraries | Open files or folders (`io` is gone) |
| Read the date and time, and measure CPU time (`os.time`, `os.date`, `os.clock`) | Run programs (`os.execute`), read environment variables, or use the rest of `os` |
| Load other `.lua` files that are inside **its own folder** (`require`) | Load libraries or C modules (`package` is gone), or compiled Lua (only text is loaded) |
| Call the `efas` API | Reach Python objects, EFAS's internals, or other plugins |
| Read and write text files in its **own data folder**, and files **you** chose in an Open or Save dialog | Read or write any other file (the API checks every path) |
| Use up to 3 seconds of CPU time per call | Run forever: after 3 seconds the call is stopped |

That makes a Lua plugin a reasonable thing to try even from someone you do not know. It is still allowed to change the photo you have open, add tags, apply presets, open other photos in the folder, and show dialogs, because those are what plugins are for.

**What the sandbox is not.** The 3-second limit and the removal of dangerous libraries are a safety net against mistakes and casual misuse. They are not a promise against a determined attacker who finds a flaw in the Lua interpreter, as with any embedded interpreter. Keep backups of anything precious whatever you install.

## Python plugins are not sandboxed

A Python plugin runs with **exactly the same access as EFAS itself**. It can read and write any file you can, start programs, use the internet and see anything EFAS can see. EFAS has no way to prevent that. It can also freeze EFAS (an endless loop) or close it (a crash).

So: **only switch on a Python plugin if you trust where it came from.** Settings > Plugins says this beside the list; it says it because it matters.

If you only need to adjust the photo, a button or a menu item, write the plugin in Lua. If you share a plugin with other people, a Lua version is safer for them.

## Protecting your photos

- Nothing in the plugin API writes to your photos. The only files a plugin can write are in its own data folder and ones **you** choose in a Save dialog (so never point a Save dialog at one of your originals). Edits made with `set_edit` are stored the way the sliders' are, as an edit you can undo, and exporting writes new files.
- A Python plugin is the exception: it can touch any file. Keep backups of anything valuable (Settings > Data & backup backs up EFAS's own database daily).
- If a plugin misbehaves: untick it in Settings > Plugins. If EFAS will not start properly because of it, move its folder out of the plugins folder (or rename it so it starts with `_`).

## Writing a plugin other people will use

- Say plainly in `description` what it does and whether it changes photos.
- Ask before doing anything that cannot be undone, with `confirm`.
- Keep your files in `data_dir`, and never write anywhere else without the user choosing the place in a dialog.
- Prefer Lua unless you need Python's libraries.
