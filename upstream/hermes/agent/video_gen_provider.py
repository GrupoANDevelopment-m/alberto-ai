"""Stub for video gen."""
class VideoGenProvider:
    def __init__(self): pass

COMMON_ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3"]

COMMON_RESOLUTIONS = ["1920x1080", "1080x1920", "1024x1024", "1280x720"]

DEFAULT_ASPECT_RATIO = "16:9"

DEFAULT_RESOLUTION = "1920x1080"

def error_response(*args, **kwargs):
    return {"error": "video gen not configured"}
