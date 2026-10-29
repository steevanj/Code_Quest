"""Sample store data for the Database tab's "Insert sample data" button.

The worker drops models and fields that don't exist yet, so this works at any point
in the curriculum.
"""

SAMPLE_CATALOG = [
    {"ref": "shoes", "model": "Category", "data": {"name": "Shoes", "slug": "shoes"}},
    {"ref": "bags", "model": "Category", "data": {"name": "Bags", "slug": "bags"}},
    {"ref": "waterproof", "model": "Tag", "data": {"name": "waterproof"}},
    {"ref": "vegan", "model": "Tag", "data": {"name": "vegan"}},
    {"ref": "p1", "model": "Product", "m2m": {"tags": ["@waterproof"]},
     "data": {"name": "Trail Runner", "slug": "trail-runner", "price": "89.00", "stock": 12, "category": "@shoes"}},
    {"ref": "p2", "model": "Product", "m2m": {"tags": ["@vegan"]},
     "data": {"name": "City Sneaker", "slug": "city-sneaker", "price": "65.00", "stock": 5, "category": "@shoes"}},
    {"ref": "p3", "model": "Product", "m2m": {"tags": ["@waterproof"]},
     "data": {"name": "Peak Boot", "slug": "peak-boot", "price": "129.00", "stock": 0, "category": "@shoes"}},
    {"ref": "p4", "model": "Product", "m2m": {"tags": ["@waterproof", "@vegan"]},
     "data": {"name": "Commuter Pack", "slug": "commuter-pack", "price": "74.50", "stock": 8, "category": "@bags"}},
    {"ref": "p5", "model": "Product", "m2m": {"tags": ["@vegan"]},
     "data": {"name": "Canvas Tote", "slug": "canvas-tote", "price": "24.00", "stock": 30, "category": "@bags"}},
]
