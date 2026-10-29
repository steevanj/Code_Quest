from django.test import SimpleTestCase

from missions.curriculum import INITIAL, MISSIONS

from .engine import analyze


class ReferenceSolutionsTests(SimpleTestCase):
    """Every mission's reference solution must analyse without errors."""

    def test_solutions_have_no_errors(self):
        for files in [INITIAL] + [m["solution"] for m in MISSIONS]:
            result = analyze(files)
            errors = [d for d in result["diagnostics"] if d["severity"] == "error"]
            self.assertEqual(errors, [], msg=errors)

    def test_relationship_becomes_edge(self):
        result = analyze({"models.py": MISSIONS[3]["solution"]["models.py"]})
        edge = next(e for e in result["edges"] if e["field"] == "Product.category")
        self.assertEqual((edge["source"], edge["target"], edge["on_delete"]),
                         ("store_product", "store_category", "PROTECT"))


class DiagnosticsTests(SimpleTestCase):
    def messages(self, **files):
        return [d["message"] for d in analyze(files)["diagnostics"]]

    def test_missing_on_delete(self):
        code = "from django.db import models\n\nclass A(models.Model):\n    pass\n\n" \
               "class B(models.Model):\n    a = models.ForeignKey(A)\n"
        self.assertTrue(any("on_delete" in m for m in self.messages(**{"models.py": code})))

    def test_model_used_before_definition(self):
        code = "from django.db import models\n\nclass B(models.Model):\n" \
               "    a = models.ForeignKey(A, on_delete=models.CASCADE)\n\nclass A(models.Model):\n    pass\n"
        self.assertTrue(any("NameError" in m for m in self.messages(**{"models.py": code})))

    def test_jsonresponse_list_needs_safe(self):
        views = "from django.http import JsonResponse\n\ndef v(request):\n    return JsonResponse([1, 2])\n"
        self.assertTrue(any("safe parameter" in m for m in self.messages(**{"views.py": views})))

    def test_n_plus_one_warning(self):
        files = dict(MISSIONS[5]["solution"])
        files["views.py"] = files["views.py"].replace('Product.objects.select_related("category")\n    data',
                                                      "Product.objects.all()\n    data")
        self.assertTrue(any("N+1" in m for m in self.messages(**files)))

    def test_unknown_serializer_field(self):
        files = dict(MISSIONS[6]["solution"])
        files["serializers.py"] = files["serializers.py"].replace('"stock", "category"', '"stok", "category"')
        self.assertTrue(any("`stok`" in m for m in self.messages(**files)))
