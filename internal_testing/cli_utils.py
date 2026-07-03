"""
Shared CLI utility functions for interactive numbered selection prompts.
"""

from __future__ import annotations

import re
from typing import Any


def prompt_input(label: str) -> str:
    """Get user input with a label."""
    return input(f"{label}: ").strip()


def prompt_numbered_selection(
    label: str,
    options: list[str],
    *,
    allow_empty: bool = False,
    empty_means_all: bool = False,
    required: bool = True,
) -> list[str]:
    """
    Prompt user to select from numbered options.
    
    Args:
        label: Prompt label
        options: List of available options
        allow_empty: Whether empty input is allowed
        empty_means_all: If True and input is empty, return all options
        required: If True, keep prompting until valid input
    
    Returns:
        List of selected options
    """
    if not options:
        if required:
            raise RuntimeError(f"No options available for: {label}")
        return []
    
    print(f"\nAvailable {label.lower()}:")
    for i, option in enumerate(options, 1):
        print(f"  {i}) {option}")
    
    empty_hint = ""
    if allow_empty and empty_means_all:
        empty_hint = f", or Enter for all"
    elif allow_empty:
        empty_hint = f", or Enter to skip"
    
    while True:
        answer = input(f"{label} (numbers, comma-separated{empty_hint}): ").strip()
        
        if not answer:
            if allow_empty:
                return options if empty_means_all else []
            if required:
                print("  Input is required. Please enter number(s).")
                continue
            return []
        
        # Parse comma-separated numbers
        try:
            selected_indices = []
            for part in answer.split(","):
                part = part.strip()
                if "-" in part:
                    # Handle ranges like "1-5"
                    start_str, end_str = part.split("-", 1)
                    start = int(start_str.strip())
                    end = int(end_str.strip())
                    if start < 1 or end > len(options) or start > end:
                        raise ValueError(f"Invalid range: {part}")
                    selected_indices.extend(range(start, end + 1))
                else:
                    # Handle single numbers
                    num = int(part)
                    if num < 1 or num > len(options):
                        raise ValueError(f"Number {num} out of range")
                    selected_indices.append(num)
            
            # Convert to options and remove duplicates while preserving order
            selected = []
            seen = set()
            for idx in selected_indices:
                option = options[idx - 1]  # Convert to 0-based
                if option not in seen:
                    selected.append(option)
                    seen.add(option)
            
            return selected
            
        except ValueError as e:
            print(f"  Invalid input: {e}")
            print(f"  Please enter numbers between 1 and {len(options)}")


def prompt_single_selection(
    label: str,
    options: list[str],
    *,
    allow_empty: bool = False,
    required: bool = True,
) -> str | None:
    """
    Prompt user to select a single option from numbered list.
    
    Returns the selected option or None if empty and allowed.
    """
    if not options:
        if required:
            raise RuntimeError(f"No options available for: {label}")
        return None
    
    if len(options) == 1:
        print(f"\n{label}: {options[0]} (only option)")
        return options[0]
    
    print(f"\nAvailable {label.lower()}:")
    for i, option in enumerate(options, 1):
        print(f"  {i}) {option}")
    
    empty_hint = ", or Enter to skip" if allow_empty else ""
    
    while True:
        answer = input(f"{label} (number{empty_hint}): ").strip()
        
        if not answer:
            if allow_empty:
                return None
            if required:
                print("  Input is required. Please enter a number.")
                continue
            return None
        
        try:
            num = int(answer)
            if num < 1 or num > len(options):
                raise ValueError(f"Number {num} out of range")
            return options[num - 1]  # Convert to 0-based
            
        except ValueError:
            print(f"  Please enter a number between 1 and {len(options)}")


def prompt_integer(
    label: str,
    *,
    min_value: int = 1,
    max_value: int | None = None,
    required: bool = True,
) -> int | None:
    """
    Prompt user for an integer value.
    
    Returns the integer or None if empty and not required.
    """
    range_hint = f" (min: {min_value}"
    if max_value is not None:
        range_hint += f", max: {max_value}"
    range_hint += ")"
    
    empty_hint = ", or Enter to skip" if not required else ""
    
    while True:
        answer = input(f"{label}{range_hint}{empty_hint}: ").strip()
        
        if not answer:
            if not required:
                return None
            print("  Input is required. Please enter a number.")
            continue
        
        try:
            value = int(answer)
            if value < min_value:
                print(f"  Value must be at least {min_value}")
                continue
            if max_value is not None and value > max_value:
                print(f"  Value must be at most {max_value}")
                continue
            return value
            
        except ValueError:
            print("  Please enter a valid integer.")


def confirm_proceed(summary: str) -> bool:
    """
    Show summary and ask for confirmation.
    
    Returns True if user confirms, False otherwise.
    """
    print(f"\n[Summary] {summary}")
    while True:
        answer = input("Proceed? (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please enter 'y' or 'n'")


def parse_persona_type(persona: str) -> str:
    """Validate and return a bare persona name (a '<type>', letters/digits only).

    Personas are named by bare type ('clueless', 'chaotic', 'cooperative').
    """
    if not re.match(r"^[a-zA-Z0-9]+$", persona):
        raise ValueError(f"Persona '{persona}' must be a bare '<type>' name (letters/digits only)")
    return persona


def group_personas_by_type(personas: list[str]) -> dict[str, list[str]]:
    """Group persona names by their type (each bare persona is its own type)."""
    groups: dict[str, list[str]] = {}
    for persona in personas:
        persona_type = parse_persona_type(persona)
        if persona_type not in groups:
            groups[persona_type] = []
        groups[persona_type].append(persona)
    return groups