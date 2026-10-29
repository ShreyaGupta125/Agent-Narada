from django.conf import settings


def asset_version(request):
    """A number that changes whenever any frontend file changes.

    Every page adds it to its CSS and JavaScript addresses, for example
    /static/header.js?v=1791049679. Browsers keep downloaded files and
    reuse them; a new number makes a new address, so after an update the
    browser downloads the new file instead of showing an old saved copy.
    """
    newest = max(
        (path.stat().st_mtime for path in settings.FRONTEND_DIR.rglob("*") if path.is_file()),
        default=0,
    )
    return {"asset_version": int(newest)}
