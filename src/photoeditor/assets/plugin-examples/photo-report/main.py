"""Photo Report: Plugins > Photo Report (Python) > Photo Report > Report on this photo.

Shows api.photo(), api.statistics() and api.save_path() / api.write_text(). Writing a file is only allowed in the plugin's own data folder or where the user chose
in a Save dialog - that is why the report goes through save_path."""


def build_report(api):
    photo = api.photo()
    if photo is None:
        return None
    lines = [
        f"{photo['name']}  ({photo['width']} x {photo['height']} px)",
        f"Film type: {photo['film_type']}, inverted: {photo['inverted']}",
        f"Exposure {photo['exposure_ev']:+.2f} EV, contrast {photo['contrast']:+.2f}",
    ]
    stats = api.statistics()
    if stats:
        lines += [
            "",
            f"Brightness: mean {stats['mean']:.0f}, median {stats['median']:.0f} (0 black, 255 white)",
            f"Range: {stats['p1']:.0f} to {stats['p99']:.0f} (the darkest and brightest 1% left out)",
            f"Tones: {stats['shadows_pct']:.1f}% shadows, {stats['midtones_pct']:.1f}% midtones, {stats['highlights_pct']:.1f}% highlights",
            f"Clipping: {stats['blocked_pct']:.1f}% blocked, {stats['blown_pct']:.1f}% blown",
        ]
    return "\n".join(lines)


def register(api):
    def show():
        report = build_report(api)
        if report is None:
            api.notify("Open a photo first")
            return
        api.info(report)
        api.message(report, "Photo report")

    def save():
        report = build_report(api)
        if report is None:
            api.notify("Open a photo first")
            return
        path = api.save_path("Save report", "photo-report.txt", "Text (*.txt)")
        if path:
            api.write_text(path, report)
            api.notify(f"Saved {path}")

    api.add_menu_item("Report on this photo", show, submenu="Photo Report")
    api.add_menu_item("Save a report...", save, submenu="Photo Report")
    api.on("photo_opened", lambda info: api.debug(f"Opened {info.get('name')}"))
