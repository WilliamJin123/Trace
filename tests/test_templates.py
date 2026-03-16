"""Tests for directive templates system."""

from __future__ import annotations

import pytest

from tract import Tract
from tract.templates import (
    BUILT_IN_TEMPLATES,
    DirectiveTemplate,
    get_template,
    list_templates,
    register_template,
)


# ---------------------------------------------------------------------------
# DirectiveTemplate.render()
# ---------------------------------------------------------------------------


class TestDirectiveTemplateRender:
    def test_render_single_param(self):
        t = DirectiveTemplate(
            name="test",
            description="test template",
            content="Hello {name}!",
            parameters={"name": "Who to greet"},
        )
        assert t.render(name="World") == "Hello World!"

    def test_render_multiple_params(self):
        t = DirectiveTemplate(
            name="test",
            description="test template",
            content="{a} and {b}",
            parameters={"a": "first", "b": "second"},
        )
        assert t.render(a="X", b="Y") == "X and Y"

    def test_render_missing_param_raises(self):
        t = DirectiveTemplate(
            name="test",
            description="test template",
            content="Hello {name}!",
            parameters={"name": "Who to greet"},
        )
        with pytest.raises(ValueError, match="Unresolved template parameters.*name"):
            t.render()

    def test_render_partial_params_raises(self):
        t = DirectiveTemplate(
            name="test",
            description="test template",
            content="{a} and {b}",
            parameters={"a": "first", "b": "second"},
        )
        with pytest.raises(ValueError, match="Unresolved.*b"):
            t.render(a="X")

    def test_render_no_params_no_placeholders(self):
        t = DirectiveTemplate(
            name="test",
            description="test template",
            content="No params here.",
        )
        assert t.render() == "No params here."

    def test_render_extra_params_ignored(self):
        t = DirectiveTemplate(
            name="test",
            description="test template",
            content="Hello {name}!",
            parameters={"name": "Who to greet"},
        )
        # Extra kwargs that aren't placeholders should not cause errors
        assert t.render(name="World", extra="unused") == "Hello World!"

    def test_render_non_string_value_converted(self):
        t = DirectiveTemplate(
            name="test",
            description="test template",
            content="Count: {n}",
            parameters={"n": "a number"},
        )
        assert t.render(n=42) == "Count: 42"

    def test_frozen_dataclass(self):
        t = DirectiveTemplate(name="x", description="d", content="c")
        with pytest.raises(AttributeError):
            t.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------


class TestBuiltInTemplates:
    """Every built-in template should render without error when all declared
    parameters are supplied."""

    EXPECTED_BUILTINS = {
        "review_protocol",
        "safety_guardrails",
        "output_format",
        "research_protocol",
        "citation_required",
        "code_review",
        "implementation_plan",
        "brand_voice",
        "conversion_optimization",
    }

    def test_all_expected_builtins_registered(self):
        assert self.EXPECTED_BUILTINS == set(BUILT_IN_TEMPLATES.keys())

    @pytest.mark.parametrize("name", sorted(BUILT_IN_TEMPLATES.keys()))
    def test_builtin_renders_with_valid_params(self, name: str):
        template = BUILT_IN_TEMPLATES[name]
        # Supply a dummy value for every declared parameter
        kwargs = {p: f"test_{p}" for p in template.parameters}
        rendered = template.render(**kwargs)
        assert isinstance(rendered, str)
        assert len(rendered) > 0
        # All placeholders should be resolved
        import re

        assert not re.findall(r"\{([^}]+)\}", rendered)

    @pytest.mark.parametrize("name", sorted(BUILT_IN_TEMPLATES.keys()))
    def test_builtin_missing_params_raises(self, name: str):
        template = BUILT_IN_TEMPLATES[name]
        if not template.parameters:
            pytest.skip("No parameters to miss")
        with pytest.raises(ValueError, match="Unresolved"):
            template.render()


# ---------------------------------------------------------------------------
# Registry functions
# ---------------------------------------------------------------------------


class TestRegistryFunctions:
    def test_list_templates_returns_all(self):
        templates = list_templates()
        assert len(templates) == len(BUILT_IN_TEMPLATES)
        names = {t.name for t in templates}
        assert names == set(BUILT_IN_TEMPLATES.keys())

    def test_get_template_found(self):
        t = get_template("code_review")
        assert t.name == "code_review"

    def test_get_template_not_found(self):
        with pytest.raises(KeyError, match="no_such_template"):
            get_template("no_such_template")

    def test_get_template_error_lists_available(self):
        with pytest.raises(KeyError, match="code_review"):
            get_template("no_such_template")

    def test_register_custom_template(self):
        custom = DirectiveTemplate(
            name="custom_test_unique_xyz",
            description="A custom template",
            content="Do {action} carefully",
            parameters={"action": "What to do"},
        )
        try:
            register_template(custom)
            retrieved = get_template("custom_test_unique_xyz")
            assert retrieved is custom
            assert retrieved in list_templates()
        finally:
            # Clean up to avoid polluting other tests
            BUILT_IN_TEMPLATES.pop("custom_test_unique_xyz", None)

    def test_register_overwrites_existing(self):
        original = get_template("code_review")
        replacement = DirectiveTemplate(
            name="code_review",
            description="Replaced",
            content="Replaced content",
        )
        try:
            register_template(replacement)
            assert get_template("code_review").description == "Replaced"
        finally:
            # Restore
            BUILT_IN_TEMPLATES["code_review"] = original


# ---------------------------------------------------------------------------
# Tract.apply_template() and Tract.list_templates()
# ---------------------------------------------------------------------------


class TestTractTemplateIntegration:
    def test_apply_template_creates_directive(self):
        with Tract.open() as t:
            info = t.templates.apply("code_review", language="Python")
            assert info.commit_hash
            assert info.message == "directive: code_review"

            # Verify the directive is in the compiled context
            ctx = t.compile()
            messages = ctx.to_dicts()
            found = any("Python" in m.get("content", "") for m in messages)
            assert found, "Rendered template content should appear in compiled context"

    def test_apply_template_custom_directive_name(self):
        with Tract.open() as t:
            info = t.templates.apply(
                "code_review", directive_name="my_review", language="Rust"
            )
            assert info.message == "directive: my_review"

    def test_apply_template_unknown_raises(self):
        with Tract.open() as t:
            with pytest.raises(KeyError, match="nonexistent"):
                t.templates.apply("nonexistent")

    def test_apply_template_missing_params_raises(self):
        with Tract.open() as t:
            with pytest.raises(ValueError, match="Unresolved"):
                t.templates.apply("safety_guardrails")  # needs domain + threshold

    def test_list_templates_from_tract(self):
        with Tract.open() as t:
            templates = t.templates.list()
            assert len(templates) >= 9
            names = {tpl.name for tpl in templates}
            assert "code_review" in names
            assert "brand_voice" in names

    def test_apply_template_directive_deduplication(self):
        """Applying the same template twice should deduplicate (latest wins)."""
        with Tract.open() as t:
            t.templates.apply("code_review", language="Python")
            t.templates.apply("code_review", language="Rust")

            ctx = t.compile()
            messages = ctx.to_dicts()
            # Only the latest (Rust) should appear
            content_str = " ".join(m.get("content", "") for m in messages)
            assert "Rust" in content_str
            # Python should be deduplicated away
            assert "Python" not in content_str

    def test_apply_template_with_multiple_params(self):
        with Tract.open() as t:
            info = t.templates.apply(
                "brand_voice",
                tone="professional",
                audience="developers",
                pillars="reliability, performance",
            )
            assert info.commit_hash
            ctx = t.compile()
            messages = ctx.to_dicts()
            content_str = " ".join(m.get("content", "") for m in messages)
            assert "professional" in content_str
            assert "developers" in content_str
            assert "reliability, performance" in content_str


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_importable_from_tract(self):
        from tract import (
            DirectiveTemplate,
            get_template,
            list_templates,
            register_template,
        )

        assert DirectiveTemplate is not None
        assert callable(get_template)
        assert callable(list_templates)
        assert callable(register_template)
