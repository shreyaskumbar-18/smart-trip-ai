from django import template
from django.templatetags.static import static

register = template.Library()


_DESTINATION_PLACEHOLDERS = {
    "chikkamagaluru": "travel/images/destination-fallback/chikkamagaluru.svg",
    "mangaluru": "travel/images/destination-fallback/mangaluru.svg",
    "udupi": "travel/images/destination-fallback/udupi.svg",
    "hampi": "travel/images/destination-fallback/hampi.svg",
    "badami": "travel/images/destination-fallback/badami.svg",
    "mysuru": "travel/images/mysuru-palace.jpg",
    "mysore": "travel/images/mysuru-palace.jpg",
}
_DESTINATION_PHOTOS = {
    "chikkamagaluru": "travel/images/destinations/chikkamagaluru.jpg",
    "mangaluru": "travel/images/destinations/mangaluru.jpg",
    "udupi": "travel/images/destinations/udupi.jpg",
    "hampi": "travel/images/destinations/hampi.jpg",
    "badami": "travel/images/destinations/badami.jpg",
}
_GENERIC_PLACEHOLDER = "travel/images/destination-fallback/destination.svg"


def _fallback_path(destination):
    name = (getattr(destination, "name", "") or "").strip().casefold()
    return static(_DESTINATION_PLACEHOLDERS.get(name, _GENERIC_PLACEHOLDER))


@register.filter
def destination_image(destination):
    """Prefer the stored image; use a destination-specific local fallback."""
    name = (getattr(destination, "name", "") or "").strip().casefold()
    # The current listing and detail pages already use this local image for
    # Mysuru; keep that behavior stable when the templates share this helper.
    if name in {"mysuru", "mysore"}:
        return static(_DESTINATION_PLACEHOLDERS[name])
    stored_image = (getattr(destination, "image_url", "") or "").strip()
    if stored_image:
        return stored_image
    if name in _DESTINATION_PHOTOS:
        return static(_DESTINATION_PHOTOS[name])
    return _fallback_path(destination)


@register.filter
def destination_image_fallback(destination):
    """Return a local fallback for a failed remote image request."""
    return _fallback_path(destination)
