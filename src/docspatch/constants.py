"""Project-wide domain constants."""

TONES: dict[str, str] = {
    "technical": "Precise; assumes domain knowledge.",
    "professional": "Clear and polished; suitable for all audiences.",
    "casual": "Friendly and approachable.",
}

LICENSE_TEXTS: dict[str, str | None] = {
    "MIT": (
        "MIT License\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        'of this software and associated documentation files (the "Software"), to deal\n'
        "in the Software without restriction, including without limitation the rights\n"
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
        "copies of the Software, and to permit persons to whom the Software is\n"
        "furnished to do so, subject to the following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all\n"
        "copies or substantial portions of the Software.\n\n"
        'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n'
        "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
        "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.\n"
    ),
    "Apache-2.0": (
        "Apache License\nVersion 2.0, January 2004\n\n"
        'Licensed under the Apache License, Version 2.0 (the "License").\n'
    ),
    "GPL-3.0": (
        "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n\n"
        "Copyright (C) 2007 Free Software Foundation, Inc.\n"
    ),
    "Proprietary": None,
}
