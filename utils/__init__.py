"""Shared utilities used across tutor, students, and judge modules."""

from .curriculum import (
    course_dir,
    discover_exercises,
    exercise_exists,
    exercise_path,
    exercises_dir,
    list_courses,
    read_exercise,
)
from .figures import (
    build_multimodal_content,
    discover_figures,
    figure_filenames,
    image_to_data_url,
    resolve_figure_filenames,
)
from .lectures import load_lecture_transcripts
from .parsing import extract_json_object
from .uploads import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_MESSAGE,
    UploadValidationError,
    ValidatedImage,
    images_to_tuples,
    validate_image,
    validate_images,
)

__all__ = [
    "extract_json_object",
    "build_multimodal_content",
    "discover_figures",
    "figure_filenames",
    "image_to_data_url",
    "resolve_figure_filenames",
    "load_lecture_transcripts",
    "course_dir",
    "discover_exercises",
    "exercise_exists",
    "exercise_path",
    "exercises_dir",
    "list_courses",
    "read_exercise",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGES_PER_MESSAGE",
    "UploadValidationError",
    "ValidatedImage",
    "images_to_tuples",
    "validate_image",
    "validate_images",
]
