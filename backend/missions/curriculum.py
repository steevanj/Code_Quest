"""The Backend Forge curriculum: one continuous e-commerce app built across missions.

Each mission's ``solution`` is the complete state of the four store files after the
mission, and the starting point of the next one. ``checks`` are declarative: the
analyzer previews them statically and the sandbox worker verifies them for real.
"""

# ----------------------------------------------------------------- reference code

INITIAL = {
    "models.py": '''from django.db import models

# Your store's database models live here.
# Every class you write becomes a table: watch the Schema tab.
''',
    "serializers.py": '''from rest_framework import serializers

# Serializers turn model instances into JSON, and validate incoming JSON.
''',
    "views.py": '''from django.http import JsonResponse

# A view receives an HttpRequest and must return an HttpResponse.
''',
    "urls.py": '''from django.urls import path

from . import views

urlpatterns = [
]
''',
}

VIEWS_HELLO = '''from django.http import JsonResponse

PRODUCTS = [
    {"id": 1, "name": "Trail Runner", "price": "89.00"},
    {"id": 2, "name": "City Sneaker", "price": "65.00"},
]


def product_list(request):
    return JsonResponse(PRODUCTS, safe=False)
'''

VIEWS_DETAIL = VIEWS_HELLO + '''

def product_detail(request, pk):
    for product in PRODUCTS:
        if product["id"] == pk:
            return JsonResponse(product)
    return JsonResponse({"detail": "Product not found."}, status=404)
'''

URLS_HELLO = '''from django.urls import path

from . import views

urlpatterns = [
    path("api/products/", views.product_list, name="product-list"),
]
'''

URLS_DETAIL = '''from django.urls import path

from . import views

urlpatterns = [
    path("api/products/", views.product_list, name="product-list"),
    path("api/products/<int:pk>/", views.product_detail, name="product-detail"),
]
'''

CATEGORY = '''class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name
'''

TAG = '''class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name
'''


def product_model(with_tags):
    tags = '    tags = models.ManyToManyField(Tag, related_name="products", blank=True)\n' if with_tags else ""
    return f'''class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )
{tags}    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
'''


CART = '''class Cart(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cart #{self.pk}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="cart_items")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="unique_product_per_cart"),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product}"
'''

HEADER = "from django.db import models\n\n\n"
MODELS_CATEGORY = HEADER + CATEGORY
MODELS_PRODUCT = HEADER + CATEGORY + "\n\n" + product_model(False)
MODELS_TAGS = HEADER + CATEGORY + "\n\n" + TAG + "\n\n" + product_model(True)
MODELS_CART = MODELS_TAGS + "\n\n" + CART

VIEWS_ORM = '''from django.http import JsonResponse

from .models import Product


def product_list(request):
    products = Product.objects.select_related("category")
    data = [
        {
            "id": p.id,
            "name": p.name,
            "price": str(p.price),
            "stock": p.stock,
            "category": p.category.name,
        }
        for p in products
    ]
    return JsonResponse(data, safe=False)


def product_detail(request, pk):
    try:
        p = Product.objects.select_related("category").get(pk=pk)
    except Product.DoesNotExist:
        return JsonResponse({"detail": "Product not found."}, status=404)
    return JsonResponse({
        "id": p.id,
        "name": p.name,
        "price": str(p.price),
        "stock": p.stock,
        "category": p.category.name,
    })
'''

SERIALIZERS_PRODUCT = '''from rest_framework import serializers

from .models import Category, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug"]


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "slug", "price", "stock", "category"]
'''

SERIALIZERS_VALIDATED = SERIALIZERS_PRODUCT + '''
    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        return value
'''

SERIALIZERS_CART = SERIALIZERS_VALIDATED.replace(
    "from .models import Category, Product", "from .models import Cart, CartItem, Category, Product"
) + '''

class CartItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = CartItem
        fields = ["id", "cart", "product", "product_name", "quantity"]

    def validate(self, attrs):
        product = attrs.get("product")
        quantity = attrs.get("quantity", 1)
        if product and quantity > product.stock:
            raise serializers.ValidationError({"quantity": f"Only {product.stock} in stock."})
        return attrs


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "created_at", "items", "total"]

    def get_total(self, cart):
        return str(sum(item.product.price * item.quantity for item in cart.items.all()))
'''

VIEWS_GENERIC = '''from rest_framework import generics

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer


class CategoryList(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ProductList(generics.ListCreateAPIView):
    queryset = Product.objects.select_related("category")
    serializer_class = ProductSerializer


class ProductDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.select_related("category")
    serializer_class = ProductSerializer
'''

VIEWS_CART = '''from rest_framework import generics, viewsets

from .models import Cart, CartItem, Category, Product
from .serializers import CartItemSerializer, CartSerializer, CategorySerializer, ProductSerializer


class CategoryList(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ProductList(generics.ListCreateAPIView):
    queryset = Product.objects.select_related("category")
    serializer_class = ProductSerializer


class ProductDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Product.objects.select_related("category")
    serializer_class = ProductSerializer


class CartViewSet(viewsets.ModelViewSet):
    queryset = Cart.objects.prefetch_related("items__product")
    serializer_class = CartSerializer


class CartItemViewSet(viewsets.ModelViewSet):
    queryset = CartItem.objects.select_related("product")
    serializer_class = CartItemSerializer
'''

URLS_GENERIC = '''from django.urls import path

from . import views

urlpatterns = [
    path("api/categories/", views.CategoryList.as_view(), name="category-list"),
    path("api/products/", views.ProductList.as_view(), name="product-list"),
    path("api/products/<int:pk>/", views.ProductDetail.as_view(), name="product-detail"),
]
'''

URLS_CART = '''from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("carts", views.CartViewSet)
router.register("cart-items", views.CartItemViewSet)

urlpatterns = [
    path("api/categories/", views.CategoryList.as_view(), name="category-list"),
    path("api/products/", views.ProductList.as_view(), name="product-list"),
    path("api/products/<int:pk>/", views.ProductDetail.as_view(), name="product-detail"),
    path("api/", include(router.urls)),
]
'''

# ------------------------------------------------------------------ check helpers

SHOES = {"ref": "shoes", "model": "Category", "data": {"name": "Shoes", "slug": "shoes"}}
CATALOG = [
    SHOES,
    {"ref": "p1", "model": "Product", "data": {"name": "Trail Runner", "slug": "trail-runner", "price": "89.00",
                                                "stock": 12, "category": "@shoes"}},
    {"ref": "p2", "model": "Product", "data": {"name": "City Sneaker", "slug": "city-sneaker", "price": "65.00",
                                                "stock": 5, "category": "@shoes"}},
    {"ref": "p3", "model": "Product", "data": {"name": "Peak Boot", "slug": "peak-boot", "price": "129.00",
                                                "stock": 0, "category": "@shoes"}},
]
NEW_PRODUCT = {"name": "Trail Runner", "slug": "trail-runner", "price": "89.00", "stock": 3, "category": "@shoes"}


def req(label, method, path, expect, body=None, setup=None):
    return {"type": "request", "label": label, "method": method, "path": path, "body": body,
            "setup": setup or [], "expect": expect}


MIGRATED = {"type": "migrations_current", "label": "Migrations are up to date (run Make migrations)"}

# ----------------------------------------------------------------------- missions

MISSIONS = [
    {
        "id": "hello-products",
        "phase": 1,
        "title": "Your first endpoint",
        "goal": "Make GET /api/products/ return a JSON list of products.",
        "story": "Every store starts with a catalog. Before any database exists, you'll trace how one HTTP request "
                 "travels through Django: URL resolver → view → response.",
        "concepts": ["URLconf", "Function views", "JsonResponse", "Status codes"],
        "focus": "views.py",
        "steps": [
            {"text": "In `views.py`, create a list `PRODUCTS` of dicts, each with `id`, `name` and `price`."},
            {"text": "Write a view `product_list(request)` that returns the list as JSON.",
             "code": "def product_list(request):\n    return JsonResponse(PRODUCTS, safe=False)"},
            {"text": "In `urls.py`, map `api/products/` to the view inside `urlpatterns`.",
             "code": 'path("api/products/", views.product_list, name="product-list"),'},
            {"text": "Open **Request flow**, send `GET /api/products/` and watch it travel. Then **Run checks**."},
        ],
        "hints": [
            "JsonResponse only accepts a dict by default — a list needs `safe=False`.",
            "Routes have no leading slash: \"api/products/\", not \"/api/products/\".",
        ],
        "requests": [{"label": "List products", "method": "GET", "path": "/api/products/"}],
        "checks": [
            req("GET /api/products/ answers 200 with a JSON list", "GET", "/api/products/",
                {"status": 200, "is_list": True}),
            req("Each product has id, name and price", "GET", "/api/products/",
                {"status": 200, "keys": ["id", "name", "price"]}),
        ],
        "solution": {**INITIAL, "views.py": VIEWS_HELLO, "urls.py": URLS_HELLO},
    },
    {
        "id": "product-detail",
        "phase": 1,
        "title": "Path parameters & 404s",
        "goal": "Add GET /api/products/<id>/ that returns one product, or 404 when it doesn't exist.",
        "story": "Customers open product pages. The URL carries the product id, and a missing product must be an "
                 "honest 404 — never a crash, never an empty 200.",
        "concepts": ["Path converters", "URL kwargs", "HTTP 404"],
        "focus": "views.py",
        "steps": [
            {"text": "Add `product_detail(request, pk)` that looks for the product whose id equals `pk`."},
            {"text": "Return it with `JsonResponse(product)`; if no product matches, return a 404.",
             "code": 'return JsonResponse({"detail": "Product not found."}, status=404)'},
            {"text": "Route it with an int converter, which passes `pk` to your view as an int.",
             "code": 'path("api/products/<int:pk>/", views.product_detail, name="product-detail"),'},
            {"text": "Try `GET /api/products/1/`, `/api/products/999/` and `/api/products/abc/`. Why is the last one "
                     "a 404 even though your view never runs?"},
        ],
        "hints": [
            "The keyword in the route (`<int:pk>`) must match the view's parameter name.",
            "`<int:pk>` only matches digits, so `abc` never reaches the view.",
        ],
        "requests": [
            {"label": "Product 1", "method": "GET", "path": "/api/products/1/"},
            {"label": "Missing product", "method": "GET", "path": "/api/products/999/"},
            {"label": "Not an int", "method": "GET", "path": "/api/products/abc/"},
        ],
        "checks": [
            req("GET /api/products/1/ returns product 1", "GET", "/api/products/1/",
                {"status": 200, "json_subset": {"id": 1}}),
            req("GET /api/products/999/ returns 404", "GET", "/api/products/999/", {"status": 404}),
            req("The list endpoint still works", "GET", "/api/products/", {"status": 200, "is_list": True}),
        ],
        "solution": {**INITIAL, "views.py": VIEWS_DETAIL, "urls.py": URLS_DETAIL},
    },
    {
        "id": "category-model",
        "phase": 2,
        "title": "Your first model: Category",
        "goal": "Define a Category model and migrate it into a real table.",
        "story": "Hard-coded lists vanish on restart. A model describes data once; Django derives a table, a query "
                 "API and validation from it. Watch the ER diagram as you type.",
        "concepts": ["models.Model", "CharField", "SlugField", "unique", "Migrations"],
        "focus": "models.py",
        "steps": [
            {"text": "In `models.py`, define `Category` with a unique `name` (max 100 characters) and a unique `slug`.",
             "code": "class Category(models.Model):\n    name = models.CharField(max_length=100, unique=True)\n"
                     "    slug = models.SlugField(unique=True)"},
            {"text": "Watch the Schema tab: the table appears as a **preview** (dashed) — it exists in code, not yet in "
                     "the database."},
            {"text": "Click **Make migrations**. Django writes `0001_initial.py`, runs its SQL, and the table turns "
                     "solid: it's now applied."},
            {"text": "Add a `__str__` method returning `self.name`, then **Run checks**."},
        ],
        "hints": [
            "CharField without max_length fails Django's system checks (fields.E120).",
            "Click any line in the editor to see what it does in the Mentor panel.",
        ],
        "requests": [],
        "checks": [
            {"type": "model", "label": "Category has a unique name (max 100 chars) and a unique slug",
             "model": "Category",
             "fields": {"name": {"type": "CharField", "max_length": 100, "unique": True},
                        "slug": {"type": "SlugField", "unique": True}}},
            MIGRATED,
        ],
        "solution": {**INITIAL, "views.py": VIEWS_DETAIL, "urls.py": URLS_DETAIL, "models.py": MODELS_CATEGORY},
    },
    {
        "id": "product-model",
        "phase": 2,
        "title": "Relationships: Product → Category",
        "goal": "Create Product with a ForeignKey to Category and see the relationship form.",
        "story": "Every product belongs to one category, and a category has many products. A ForeignKey stores "
                 "`category_id` on the product row — one source of truth for category data.",
        "concepts": ["ForeignKey", "on_delete", "related_name", "DecimalField", "PositiveIntegerField"],
        "focus": "models.py",
        "steps": [
            {"text": "Below Category, define `Product` with `name`, a unique `slug`, `price` "
                     "(DecimalField, 10 digits, 2 decimals) and `stock` (PositiveIntegerField, default 0)."},
            {"text": "Connect it to Category, protecting categories that still have products.",
             "code": "category = models.ForeignKey(\n    Category,\n    on_delete=models.PROTECT,\n"
                     "    related_name=\"products\",\n)"},
            {"text": "Add `created_at = models.DateTimeField(auto_now_add=True)` and a `__str__`."},
            {"text": "Watch the arrow appear in the ER diagram, then **Make migrations** to create `0002`."},
        ],
        "hints": [
            "Product must come *after* Category in the file (or use the string \"Category\").",
            "Click the `on_delete` line — the Mentor has a question for you.",
        ],
        "requests": [],
        "checks": [
            {"type": "model", "label": "Product has name, price (10, 2) and stock fields", "model": "Product",
             "fields": {"name": {"type": "CharField", "max_length": 200},
                        "price": {"type": "DecimalField", "max_digits": 10, "decimal_places": 2},
                        "stock": {"type": "PositiveIntegerField"}}},
            {"type": "model", "label": "Product.category is a protected ForeignKey with related_name=\"products\"",
             "model": "Product",
             "fields": {"category": {"type": "ForeignKey", "to": "Category", "on_delete": "PROTECT",
                                     "related_name": "products"}}},
            MIGRATED,
        ],
        "solution": {**INITIAL, "views.py": VIEWS_DETAIL, "urls.py": URLS_DETAIL, "models.py": MODELS_PRODUCT},
    },
    {
        "id": "tags-m2m",
        "phase": 2,
        "title": "Many-to-many: product tags",
        "goal": "Tag products (\"waterproof\", \"vegan\"...) with a ManyToManyField.",
        "story": "A product can have many tags, and a tag many products. No single column can hold that — so Django "
                 "creates a hidden junction table. You'll see it appear in the diagram.",
        "concepts": ["ManyToManyField", "Junction tables", "blank=True"],
        "focus": "models.py",
        "steps": [
            {"text": "Define `Tag` with a unique `name` (max 50) *above* Product."},
            {"text": "Add to Product:",
             "code": 'tags = models.ManyToManyField(Tag, related_name="products", blank=True)'},
            {"text": "Notice the new `store_product_tags` table in the Schema tab — that's where links live."},
            {"text": "**Make migrations**, then **Run checks**."},
        ],
        "hints": ["blank=True lets a product have zero tags. null has no effect on ManyToManyField."],
        "requests": [],
        "checks": [
            {"type": "model", "label": "Tag has a unique name", "model": "Tag",
             "fields": {"name": {"type": "CharField", "unique": True}}},
            {"type": "model", "label": "Product.tags is a ManyToManyField to Tag", "model": "Product",
             "fields": {"tags": {"type": "ManyToManyField", "to": "Tag"}}},
            MIGRATED,
        ],
        "solution": {**INITIAL, "views.py": VIEWS_DETAIL, "urls.py": URLS_DETAIL, "models.py": MODELS_TAGS},
    },
    {
        "id": "orm-views",
        "phase": 2,
        "title": "Query the ORM (and kill N+1)",
        "goal": "Serve products from the database instead of the hard-coded list, in a single SQL query.",
        "story": "Time to delete PRODUCTS. Your views will query the database through the ORM — and you'll meet the "
                 "most common performance bug in Django: N+1 queries.",
        "concepts": ["QuerySets", "Lazy evaluation", ".get()", "DoesNotExist", "select_related", "N+1"],
        "focus": "views.py",
        "steps": [
            {"text": "Import the model: `from .models import Product`, and delete the PRODUCTS list."},
            {"text": "In `product_list`, build a list of dicts from `Product.objects.all()` — include "
                     "`p.category.name`."},
            {"text": "Use the Database tab to add a category and a few products (or POST them later), send "
                     "`GET /api/products/` and count the SQL queries in Request flow. One per product = N+1!"},
            {"text": "Fix it with a JOIN:", "code": 'products = Product.objects.select_related("category")'},
            {"text": "Rewrite `product_detail` with `.get(pk=pk)`, returning 404 on `Product.DoesNotExist`."},
        ],
        "hints": [
            "`str(p.price)` — Decimal isn't JSON serializable by JsonResponse.",
            "The analyzer flags N+1 loops as a warning in the editor.",
        ],
        "requests": [
            {"label": "List products", "method": "GET", "path": "/api/products/"},
            {"label": "Product 1", "method": "GET", "path": "/api/products/1/"},
        ],
        "checks": [
            req("GET /api/products/ lists the 3 products from the database", "GET", "/api/products/",
                {"status": 200, "length": 3, "keys": ["id", "name", "price", "category"]}, setup=CATALOG),
            req("The list runs a single SQL query (no N+1)", "GET", "/api/products/",
                {"status": 200, "max_queries": 1}, setup=CATALOG),
            req("GET /api/products/<id>/ reads the product from the database", "GET", "/api/products/@p1/",
                {"status": 200, "json_subset": {"name": "Trail Runner"}}, setup=CATALOG),
            req("A missing product returns 404", "GET", "/api/products/9999/", {"status": 404}, setup=CATALOG),
            MIGRATED,
        ],
        "solution": {**INITIAL, "views.py": VIEWS_ORM, "urls.py": URLS_DETAIL, "models.py": MODELS_TAGS},
    },
    {
        "id": "product-api",
        "phase": 3,
        "title": "Serializers & generic views",
        "goal": "Replace hand-written JSON with ModelSerializers and DRF generic views — including POST.",
        "story": "Hand-building dicts doesn't scale and doesn't validate. A serializer is the gate between raw JSON "
                 "and your models; generic views wire it to a queryset.",
        "concepts": ["ModelSerializer", "Meta.fields", "ListCreateAPIView", "RetrieveUpdateDestroyAPIView", "201/400"],
        "focus": "serializers.py",
        "steps": [
            {"text": "In `serializers.py`, write `CategorySerializer` and `ProductSerializer`.",
             "code": "class ProductSerializer(serializers.ModelSerializer):\n    class Meta:\n        model = Product\n"
                     "        fields = [\"id\", \"name\", \"slug\", \"price\", \"stock\", \"category\"]"},
            {"text": "In `views.py`, replace your functions with `CategoryList` and `ProductList` "
                     "(ListCreateAPIView) and `ProductDetail` (RetrieveUpdateDestroyAPIView)."},
            {"text": "Route them with `.as_view()`, including `api/categories/`."},
            {"text": "POST a category, then a product, and watch validation → save → INSERT in Request flow. "
                     "Then POST `{}` and read the 400 errors."},
        ],
        "hints": [
            "A serializer never writes by itself: the view calls is_valid() and then save().",
            "`category` in a ModelSerializer expects the category's id.",
        ],
        "requests": [
            {"label": "Create category", "method": "POST", "path": "/api/categories/",
             "body": {"name": "Shoes", "slug": "shoes"}},
            {"label": "Create product", "method": "POST", "path": "/api/products/",
             "body": {"name": "Trail Runner", "slug": "trail-runner", "price": "89.00", "stock": 12, "category": 1}},
            {"label": "Invalid product", "method": "POST", "path": "/api/products/", "body": {"price": "abc"}},
            {"label": "List products", "method": "GET", "path": "/api/products/"},
        ],
        "checks": [
            {"type": "serializer", "label": "ProductSerializer exposes id, name, price and category",
             "serializer": "ProductSerializer", "model": "Product", "fields": ["id", "name", "price", "category"]},
            req("POST /api/categories/ creates a category (201)", "POST", "/api/categories/",
                {"status": 201, "json_subset": {"slug": "bags"}}, body={"name": "Bags", "slug": "bags"}),
            req("POST /api/products/ creates a product (201)", "POST", "/api/products/",
                {"status": 201, "keys": ["id"], "db_count": {"model": "Product", "count": 1}},
                body=NEW_PRODUCT, setup=[SHOES]),
            req("POST with missing fields returns 400 with errors", "POST", "/api/products/",
                {"status": 400, "error_keys": ["name", "category"]}, body={"price": "10.00"}),
            req("GET /api/products/ lists products", "GET", "/api/products/", {"status": 200, "length": 3},
                setup=CATALOG),
            req("GET /api/products/<id>/ retrieves one product", "GET", "/api/products/@p1/",
                {"status": 200, "json_subset": {"name": "Trail Runner"}}, setup=CATALOG),
        ],
        "solution": {"models.py": MODELS_TAGS, "serializers.py": SERIALIZERS_PRODUCT, "views.py": VIEWS_GENERIC,
                     "urls.py": URLS_GENERIC},
    },
    {
        "id": "validation",
        "phase": 3,
        "title": "Validation rules",
        "goal": "Reject products whose price isn't greater than zero — on create and on update.",
        "story": "The database happily stores a price of -5. Business rules belong at the API boundary, before "
                 "anything is saved.",
        "concepts": ["validate_<field>", "ValidationError", "400 responses", "PATCH"],
        "focus": "serializers.py",
        "steps": [
            {"text": "In ProductSerializer, add a field-level validator:",
             "code": "def validate_price(self, value):\n    if value <= 0:\n"
                     "        raise serializers.ValidationError(\"Price must be greater than zero.\")\n    return value"},
            {"text": "POST a product with price `-5.00` and see the serializer stage turn red in Request flow."},
            {"text": "PATCH an existing product with a negative price — the same rule protects updates."},
        ],
        "hints": ["Forgetting `return value` makes DRF save None as the price."],
        "requests": [
            {"label": "Negative price", "method": "POST", "path": "/api/products/",
             "body": {"name": "Broken", "slug": "broken", "price": "-5.00", "stock": 1, "category": 1}},
            {"label": "PATCH price", "method": "PATCH", "path": "/api/products/1/", "body": {"price": "-1.00"}},
        ],
        "checks": [
            req("A negative price is rejected with a price error", "POST", "/api/products/",
                {"status": 400, "error_keys": ["price"]}, body={**NEW_PRODUCT, "price": "-5.00"}, setup=[SHOES]),
            req("A price of 0.00 is rejected", "POST", "/api/products/",
                {"status": 400, "error_keys": ["price"]}, body={**NEW_PRODUCT, "price": "0.00"}, setup=[SHOES]),
            req("A valid product is still created", "POST", "/api/products/", {"status": 201},
                body=NEW_PRODUCT, setup=[SHOES]),
            req("PATCH with a negative price is rejected", "PATCH", "/api/products/@p1/",
                {"status": 400, "error_keys": ["price"]}, body={"price": "-1.00"}, setup=CATALOG),
        ],
        "solution": {"models.py": MODELS_TAGS, "serializers.py": SERIALIZERS_VALIDATED, "views.py": VIEWS_GENERIC,
                     "urls.py": URLS_GENERIC},
    },
    {
        "id": "cart-models",
        "phase": 3,
        "title": "Cart & CartItem models",
        "goal": "Model shopping carts: a Cart has many CartItems, each pointing at a Product.",
        "story": "A cart item links a cart to a product with a quantity. Deleting a cart should delete its items, "
                 "but deleting a product someone has in a cart should be blocked — and a product can only appear "
                 "once per cart.",
        "concepts": ["CASCADE vs PROTECT", "UniqueConstraint", "Meta.constraints"],
        "focus": "models.py",
        "steps": [
            {"text": "Add `Cart` with `created_at = models.DateTimeField(auto_now_add=True)`."},
            {"text": "Add `CartItem` with `cart` (FK → Cart, CASCADE, related_name \"items\"), `product` "
                     "(FK → Product, PROTECT) and `quantity` (PositiveIntegerField, default 1)."},
            {"text": "Stop duplicate rows with a constraint in CartItem's Meta:",
             "code": "class Meta:\n    constraints = [\n        models.UniqueConstraint(\n"
                     "            fields=[\"cart\", \"product\"], name=\"unique_product_per_cart\"\n        ),\n    ]"},
            {"text": "**Make migrations** and read the generated SQL in the Database tab."},
        ],
        "hints": ["Constraints must have a name.", "Compare the CASCADE and PROTECT arrows in the ER diagram."],
        "requests": [],
        "checks": [
            {"type": "model", "label": "Cart has a created_at timestamp", "model": "Cart",
             "fields": {"created_at": {"type": "DateTimeField"}}},
            {"type": "model", "label": "CartItem links cart (CASCADE, items) and product (PROTECT)",
             "model": "CartItem",
             "fields": {"cart": {"type": "ForeignKey", "to": "Cart", "on_delete": "CASCADE", "related_name": "items"},
                        "product": {"type": "ForeignKey", "to": "Product", "on_delete": "PROTECT"},
                        "quantity": {"type": "PositiveIntegerField"}}},
            {"type": "unique_together", "label": "A product appears at most once per cart", "model": "CartItem",
             "fields": ["cart", "product"]},
            MIGRATED,
        ],
        "solution": {"models.py": MODELS_CART, "serializers.py": SERIALIZERS_VALIDATED, "views.py": VIEWS_GENERIC,
                     "urls.py": URLS_GENERIC},
    },
    {
        "id": "cart-api",
        "phase": 3,
        "title": "Cart API: nesting, ViewSets & routers",
        "goal": "Expose carts with nested items and a computed total, and stop customers adding more than is in stock.",
        "story": "This is the milestone: a working cart API. You'll nest serializers, compute values, validate across "
                 "fields, and let a router generate URLs for ViewSets.",
        "concepts": ["Nested serializers", "SerializerMethodField", "validate()", "ModelViewSet", "DefaultRouter",
                     "prefetch_related"],
        "focus": "serializers.py",
        "steps": [
            {"text": "Write `CartItemSerializer` (with `product_name` read from `product.name`) and a `validate()` "
                     "that rejects quantities above `product.stock`."},
            {"text": "Write `CartSerializer` with nested `items` and a `total` SerializerMethodField.",
             "code": "items = CartItemSerializer(many=True, read_only=True)\ntotal = serializers.SerializerMethodField()"},
            {"text": "Add `CartViewSet` and `CartItemViewSet` (ModelViewSet). Use "
                     "`Cart.objects.prefetch_related(\"items__product\")`."},
            {"text": "Register both on a `DefaultRouter` and include `router.urls` under `api/`."},
            {"text": "Create a cart, add an item, then GET the cart and watch the queries."},
        ],
        "hints": [
            "Nested serializers must be defined above the serializer that uses them.",
            "Without prefetch_related, every item triggers more queries to compute the total.",
        ],
        "requests": [
            {"label": "Create cart", "method": "POST", "path": "/api/carts/", "body": {}},
            {"label": "Add item", "method": "POST", "path": "/api/cart-items/",
             "body": {"cart": 1, "product": 1, "quantity": 2}},
            {"label": "View cart", "method": "GET", "path": "/api/carts/1/"},
        ],
        "checks": [
            {"type": "serializer", "label": "CartSerializer exposes id, items and total",
             "serializer": "CartSerializer", "model": "Cart", "fields": ["id", "items", "total"]},
            req("POST /api/carts/ creates a cart", "POST", "/api/carts/", {"status": 201, "keys": ["id"]}, body={}),
            req("POST /api/cart-items/ adds a product to a cart", "POST", "/api/cart-items/",
                {"status": 201, "json_subset": {"quantity": 2}},
                body={"cart": "@c1", "product": "@p1", "quantity": 2},
                setup=CATALOG + [{"ref": "c1", "model": "Cart", "data": {}}]),
            req("Adding more than the stock returns 400", "POST", "/api/cart-items/",
                {"status": 400, "error_keys": ["quantity"]},
                body={"cart": "@c1", "product": "@p1", "quantity": 50},
                setup=CATALOG + [{"ref": "c1", "model": "Cart", "data": {}}]),
            req("GET /api/carts/<id>/ shows items and the total in ≤ 3 queries", "GET", "/api/carts/@c1/",
                {"status": 200, "keys": ["items", "total"], "json_subset": {"total": "243.00"}, "max_queries": 3},
                setup=CATALOG + [
                    {"ref": "c1", "model": "Cart", "data": {}},
                    {"ref": "i1", "model": "CartItem", "data": {"cart": "@c1", "product": "@p1", "quantity": 2}},
                    {"ref": "i2", "model": "CartItem", "data": {"cart": "@c1", "product": "@p2", "quantity": 1}},
                ]),
        ],
        "solution": {"models.py": MODELS_CART, "serializers.py": SERIALIZERS_CART, "views.py": VIEWS_CART,
                     "urls.py": URLS_CART},
    },
]

PHASES = [
    {"id": 1, "title": "Foundation & Request Lifecycle", "level": "Beginner", "build": "The basic store backend",
     "visual": "Browser request → URL resolver → View → Response",
     "milestone": "GET /api/products/ returns a valid response."},
    {"id": 2, "title": "Database & ORM", "level": "Data engineering", "build": "The product catalog and inventory",
     "visual": "Model code → ER diagram → migration → database schema",
     "milestone": "Products are stored, related to categories, filtered and retrieved."},
    {"id": 3, "title": "REST API & Serializers", "level": "API design", "build": "A product and cart API",
     "visual": "JSON → serializer validation → view → ORM → database → JSON",
     "milestone": "Create products, retrieve them and manage a cart through APIs."},
    {"id": 4, "title": "Authentication & Business Logic", "level": "Coming soon", "locked": True,
     "build": "Customer accounts, checkout and orders",
     "visual": "User → permission check → checkout service → transaction → order records",
     "milestone": "Customers place orders without seeing each other's data or overselling stock.",
     "topics": ["JWT login & refresh", "Ownership permissions", "Order & OrderItem", "transaction.atomic()",
                "select_for_update()"]},
    {"id": 5, "title": "Testing & Performance", "level": "Coming soon", "locked": True,
     "build": "A reliable e-commerce system", "visual": "Tests flowing through the system, SQL counts, bottlenecks",
     "milestone": "The API survives realistic tests and failure scenarios.",
     "topics": ["APITestCase", "Invalid payloads", "Concurrency", "Caching with Redis", "Celery tasks"]},
    {"id": 6, "title": "Production Deployment", "level": "Coming soon", "locked": True,
     "build": "A deployable e-commerce backend", "visual": "Commit → build → tests → deploy → live health",
     "milestone": "Deploy a tested backend and understand how requests reach it.",
     "topics": ["PostgreSQL", "Environment secrets", "Docker", "CI/CD", "OpenAPI docs"]},
]

_BY_ID = {m["id"]: m for m in MISSIONS}


def get_mission(mission_id):
    return _BY_ID.get(mission_id)


def starting_files(mission_id):
    """The reference code a mission starts from: the previous mission's solution."""
    index = next(i for i, m in enumerate(MISSIONS) if m["id"] == mission_id)
    return dict(MISSIONS[index - 1]["solution"]) if index else dict(INITIAL)


def curriculum():
    phases = []
    for phase in PHASES:
        missions = [{**m, "start": starting_files(m["id"])} for m in MISSIONS if m["phase"] == phase["id"]]
        phases.append({**phase, "missions": missions})
    return {"initial": INITIAL, "phases": phases}
