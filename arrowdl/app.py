"""ArrowDL application entry."""

from __future__ import annotations

import sys


def main() -> None:
    # Ensure package imports work when run as script
    from arrowdl.config import ensure_category_dirs, get_default_download_base
    from arrowdl.db import Database
    from arrowdl.engine import DownloadEngine
    from arrowdl.ui import theme
    from arrowdl.ui.main_window import MainWindow

    theme.apply_theme()
    get_default_download_base()

    db = Database()
    settings = db.get_settings()
    ensure_category_dirs(
        settings.base_download_folder,
        {
            "Software": settings.category_software,
            "Docs": settings.category_docs,
            "Videos": settings.category_videos,
            "Other": settings.category_other,
        },
    )

    engine = DownloadEngine(db)
    engine.start()

    app = MainWindow(engine)
    try:
        app.mainloop()
    finally:
        engine.stop()
        db.close()


if __name__ == "__main__":
    main()
