# The manifest (`plugin.json`)

Every plugin folder needs a `plugin.json` next to its program. It is read when EFAS starts, when you open **Settings > Plugins**, and when you press **Look for plugins again**.

```json
{
  "id": "com.example.hello",
  "name": "Hello",
  "version": "1.2",
  "author": "A. Person",
  "description": "Says hello.",
  "entry": "main.lua",
  "language": "lua",
  "api": 1
}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | A unique name for the plugin: 2 to 64 lower-case letters, digits, dots, dashes and underscores, starting with a letter or digit (`com.example.hello`, `user.my-tool`). EFAS remembers whether a plugin is switched on by its id, and gives it its own data folder named after it. Upper-case letters are turned into lower case. |
| `name` | no | What the plugin is called in menus, in Settings and in the Plugin Output window. Up to 60 characters. Defaults to the id. |
| `version` | no | Free text, shown in Settings. Defaults to `0`. |
| `author` | no | Shown in Settings. |
| `description` | no | One or two sentences, shown under the plugin's name in Settings. |
| `entry` | no | The program's file, inside the plugin folder: a `.py` or a `.lua` file. If you leave it out, EFAS uses `main.py` or `main.lua`, whichever exists. |
| `language` | no | `python` or `lua`. It is worked out from `entry`; if you write it, it must agree. |
| `api` | no | The lowest plugin API version the plugin needs. Defaults to 1. A plugin that needs more than this EFAS has is listed as unusable. |

## When a plugin is "not a usable plugin"

Settings > Plugins lists every folder in the plugins folder. A folder whose manifest is wrong is shown with the reason in plain words, for example:

- *There is no plugin.json in this folder.*
- *plugin.json could not be read* (the JSON is broken; the reason follows).
- *plugin.json needs an "id" of 2 to 64 letters...*
- *The entry "../x.lua" must be a file inside the plugin's own folder.*
- *The entry file "main.lua" is not in the plugin's folder.*
- *It needs plugin API 2 but this EFAS has 1: update EFAS to use it.*
- *Another plugin folder already uses the id "..."* (two folders with the same id: the first, in alphabetical order, wins).

Folders whose names begin with `.` or `_` are ignored, so `_old-version` is a safe place to park a copy.

## Files in the plugin folder

A plugin may have any other files it likes next to its program: more Lua files (loaded with `require`), more Python files (loaded with `import`), data it ships with. Its own *saved* settings and files do not go there; they go in its data folder (see [the API reference](api-reference.md#settings-and-files)).

## Where plugins live

| What | Where |
|---|---|
| Plugins | `<EFAS data folder>\plugins\<folder>` |
| A plugin's saved settings and files | `<EFAS data folder>\plugin-data\<plugin id>` |
| Which plugins are switched on | EFAS's settings file (`plugins_enabled`) |

The data folder is `C:\Users\<you>\.EFAS` unless you moved it. **Settings > Plugins > Open plugins folder** opens the first of these.

To share a plugin, zip its folder. To install one someone sent you, unzip it into the plugins folder so that `plugin.json` sits directly inside its own folder, then press **Look for plugins again**.
