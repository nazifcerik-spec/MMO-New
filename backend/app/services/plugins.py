"""Import every module that registers providers/hooks so they are active in all entry points."""

import app.services.classes
import app.services.content.types
import app.services.crafting
import app.services.goals
import app.services.inventory
import app.services.items
import app.services.races
import app.services.tactics
import app.services.talents  # noqa: F401
