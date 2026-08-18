
from .models import PlatformConfig


def platform(request):
    try:
        config = PlatformConfig.get_solo()
    except Exception:
        config = None
    return {'platform_config': config}
