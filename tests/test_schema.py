"""Tests for schema definitions."""

from iga_connector.core.schema import (
    AttributeSchema,
    AttributeType,
    ConnectorSchema,
    ObjectSchema,
)


class TestAttributeSchema:
    def test_auto_display_name(self):
        attr = AttributeSchema(name="first_name")
        assert attr.display_name == "First Name"

    def test_explicit_display_name(self):
        attr = AttributeSchema(name="fn", display_name="First Name")
        assert attr.display_name == "First Name"

    def test_defaults(self):
        attr = AttributeSchema(name="email")
        assert attr.attr_type == AttributeType.STRING
        assert attr.required is False
        assert attr.multi_valued is False
        assert attr.readonly is False


class TestObjectSchema:
    def test_get_attribute(self):
        schema = ObjectSchema(
            object_type="account",
            attributes=[
                AttributeSchema(name="id", required=True),
                AttributeSchema(name="email"),
            ],
        )
        assert schema.get_attribute("id") is not None
        assert schema.get_attribute("nonexistent") is None

    def test_required_attributes(self):
        schema = ObjectSchema(
            object_type="account",
            attributes=[
                AttributeSchema(name="id", required=True),
                AttributeSchema(name="name", required=True),
                AttributeSchema(name="email"),
            ],
        )
        required = schema.required_attributes()
        assert len(required) == 2


class TestConnectorSchema:
    def test_get_object_schema(self):
        cs = ConnectorSchema(
            connector_name="test",
            object_schemas=[
                ObjectSchema(object_type="account"),
                ObjectSchema(object_type="entitlement"),
            ],
        )
        assert cs.get_object_schema("account") is not None
        assert cs.get_object_schema("missing") is None
