from abc import ABCMeta, abstractmethod, abstractproperty
from collections.abc import Mapping

from amaranth.hdl import *
from amaranth.hdl.ast import ShapeCastable, ValueCastable


__all__ = [
    "Field", "Layout", "StructLayout", "UnionLayout", "ArrayLayout", "FlexibleLayout",
    "View", "Struct", "Union",
]


class Field:
    def __init__(self, shape, offset):
        self.shape  = shape
        self.offset = offset

    @property
    def shape(self):
        return self._shape

    @shape.setter
    def shape(self, shape):
        try:
            Shape.cast(shape)
        except TypeError as e:
            raise TypeError("Field shape must be a shape-castable object, not {!r}"
                            .format(shape)) from e
        self._shape = shape

    @property
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, offset):
        if not isinstance(offset, int) or offset < 0:
            raise TypeError("Field offset must be a non-negative integer, not {!r}"
                            .format(offset))
        self._offset = offset

    @property
    def width(self):
        return Shape.cast(self.shape).width

    def __eq__(self, other):
        return (isinstance(other, Field) and
                self._shape == other.shape and self._offset == other.offset)

    def __repr__(self):
        return f"Field({self._shape!r}, {self._offset})"


class Layout(ShapeCastable, metaclass=ABCMeta):
    @staticmethod
    def cast(obj):
        """Cast a shape-castable object to a layout."""
        while isinstance(obj, ShapeCastable):
            if isinstance(obj, Layout):
                return obj
            new_obj = obj.as_shape()
            if new_obj is obj:
                break
            obj = new_obj
        Shape.cast(obj) # delegate non-layout-specific error handling to Shape
        raise TypeError("Object {!r} cannot be converted to a data layout"
                        .format(obj))

    @staticmethod
    def of(obj):
        """Extract the layout from a view."""
        if not isinstance(obj, View):
            raise TypeError("Object {!r} is not a data view"
                            .format(obj))
        return obj._View__orig_layout

    @abstractmethod
    def __iter__(self):
        """Iterate the layout, yielding ``(key, field)`` pairs. Keys may be strings or integers."""

    @abstractmethod
    def __getitem__(self, key):
        """Retrieve the :class:`Field` associated with the ``key``, or raise ``KeyError``."""

    size = abstractproperty()
    """The number of bits in the representation defined by the layout."""

    def as_shape(self):
        """Convert the representation defined by the layout to an unsigned :class:`Shape`."""
        return unsigned(self.size)

    def __eq__(self, other):
        """Compare the layout with another.

        Two layouts are equal if they have the same size and the same fields under the same names.
        The order of the fields is not considered.
        """
        while isinstance(other, ShapeCastable) and not isinstance(other, Layout):
            new_other = other.as_shape()
            if new_other is other:
                break
            other = new_other
        return (isinstance(other, Layout) and self.size == other.size and
                dict(iter(self)) == dict(iter(other)))


class StructLayout(Layout):
    def __init__(self, members):
        self.members = members

    @property
    def members(self):
        return {key: field.shape for key, field in self._fields.items()}

    @members.setter
    def members(self, members):
        offset = 0
        self._fields = {}
        if not isinstance(members, Mapping):
            raise TypeError("Struct layout members must be provided as a mapping, not {!r}"
                            .format(members))
        for key, shape in members.items():
            if not isinstance(key, str):
                raise TypeError("Struct layout member name must be a string, not {!r}"
                                .format(key))
            try:
                cast_shape = Shape.cast(shape)
            except TypeError as e:
                raise TypeError("Struct layout member shape must be a shape-castable object, "
                                "not {!r}"
                                .format(shape)) from e
            self._fields[key] = Field(shape, offset)
            offset += cast_shape.width

    def __iter__(self):
        return iter(self._fields.items())

    def __getitem__(self, key):
        return self._fields[key]

    @property
    def size(self):
        return max((field.offset + field.width for field in self._fields.values()), default=0)

    def __repr__(self):
        return f"StructLayout({self.members!r})"


class UnionLayout(Layout):
    def __init__(self, members):
        self.members = members

    @property
    def members(self):
        return {key: field.shape for key, field in self._fields.items()}

    @members.setter
    def members(self, members):
        self._fields = {}
        if not isinstance(members, Mapping):
            raise TypeError("Union layout members must be provided as a mapping, not {!r}"
                            .format(members))
        for key, shape in members.items():
            if not isinstance(key, str):
                raise TypeError("Union layout member name must be a string, not {!r}"
                                .format(key))
            try:
                cast_shape = Shape.cast(shape)
            except TypeError as e:
                raise TypeError("Union layout member shape must be a shape-castable object, "
                                "not {!r}"
                                .format(shape)) from e
            self._fields[key] = Field(shape, 0)

    def __iter__(self):
        return iter(self._fields.items())

    def __getitem__(self, key):
        return self._fields[key]

    @property
    def size(self):
        return max((field.width for field in self._fields.values()), default=0)

    def __repr__(self):
        return f"UnionLayout({self.members!r})"


class ArrayLayout(Layout):
    def __init__(self, elem_shape, length):
        self.elem_shape = elem_shape
        self.length     = length

    @property
    def elem_shape(self):
        return self._elem_shape

    @elem_shape.setter
    def elem_shape(self, elem_shape):
        try:
            Shape.cast(elem_shape)
        except TypeError as e:
            raise TypeError("Array layout element shape must be a shape-castable object, "
                            "not {!r}"
                            .format(elem_shape)) from e
        self._elem_shape = elem_shape

    @property
    def length(self):
        return self._length

    @length.setter
    def length(self, length):
        if not isinstance(length, int) or length < 0:
            raise TypeError("Array layout length must be a non-negative integer, not {!r}"
                            .format(length))
        self._length = length

    def __iter__(self):
        offset = 0
        for index in range(self._length):
            yield index, Field(self._elem_shape, offset)
            offset += self._elem_shape.width

    def __getitem__(self, key):
        if isinstance(key, int):
            if key not in range(-self._length, self._length):
                # Layout's interface requires us to raise KeyError, not IndexError
                raise KeyError(key)
            if key < 0:
                key += self._length
            return Field(self._elem_shape, key * self._elem_shape.width)
        raise TypeError("Cannot index array layout with {!r}".format(key))

    @property
    def size(self):
        return self._elem_shape.width * self.length

    def __repr__(self):
        return f"ArrayLayout({self._elem_shape!r}, {self.length})"


class FlexibleLayout(Layout):
    def __init__(self, size, fields):
        self.size   = size
        self.fields = fields

    @property
    def size(self):
        return self._size

    @size.setter
    def size(self, size):
        if not isinstance(size, int) or size < 0:
            raise TypeError("Flexible layout size must be a non-negative integer, not {!r}"
                            .format(size))
        if hasattr(self, "_fields") and self._fields:
            endmost_name, endmost_field = max(self._fields.items(),
                key=lambda pair: pair[1].offset + pair[1].width)
            if endmost_field.offset + endmost_field.width > size:
                raise ValueError("Flexible layout size {} does not cover the field '{}', which "
                                 "ends at bit {}"
                                 .format(size, endmost_name,
                                         endmost_field.offset + endmost_field.width))
        self._size = size

    @property
    def fields(self):
        return {**self._fields}

    @fields.setter
    def fields(self, fields):
        self._fields = {}
        if not isinstance(fields, Mapping):
            raise TypeError("Flexible layout fields must be provided as a mapping, not {!r}"
                            .format(fields))
        for key, field in fields.items():
            if not isinstance(key, (int, str)) or (isinstance(key, int) and key < 0):
                raise TypeError("Flexible layout field name must be a non-negative integer or "
                                "a string, not {!r}"
                                .format(key))
            if not isinstance(field, Field):
                raise TypeError("Flexible layout field value must be a Field instance, not {!r}"
                                .format(field))
            if field.offset + field.width > self._size:
                raise ValueError("Flexible layout field '{}' ends at bit {}, exceeding "
                                 "the size of {} bit(s)"
                                 .format(key, field.offset + field.width, self._size))
            self._fields[key] = field

    def __iter__(self):
        return iter(self._fields.items())

    def __getitem__(self, key):
        if isinstance(key, (int, str)):
            return self._fields[key]
        raise TypeError("Cannot index flexible layout with {!r}".format(key))

    def __repr__(self):
        return f"FlexibleLayout({self._size}, {self._fields!r})"


class View(ValueCastable):
    def __init__(self, layout, value=None, *, src_loc_at=0):
        try:
            cast_layout = Layout.cast(layout)
        except TypeError:
            raise TypeError("View layout must be a Layout instance, not {!r}"
                            .format(layout))
        if value is not None:
            try:
                cast_value = Value.cast(value)
            except TypeError:
                raise TypeError("View target must be a value-castable object, not {!r}"
                                .format(value))
            if len(cast_value) != cast_layout.size:
                raise ValueError("View target is {} bit(s) wide, which is not compatible with "
                                 "the {} bit(s) wide view layout"
                                 .format(len(cast_value), cast_layout.size))
        else:
            cast_value = Signal(cast_layout, src_loc_at=src_loc_at + 1)
        self.__orig_layout = layout
        self.__layout = cast_layout
        self.__value  = cast_value

    @ValueCastable.lowermethod
    def as_value(self):
        return self.__value

    def eq(self, other):
        return self.as_value().eq(other)

    def __getitem__(self, key):
        if isinstance(self.__layout, ArrayLayout):
            shape = self.__layout.elem_shape
            value = self.__value.word_select(key, self.__layout.elem_shape.width)
        else:
            if isinstance(key, (Value, ValueCastable)):
                raise TypeError("Only views with array layout, not {!r}, may be indexed "
                                "with a value"
                                .format(self.__layout))
            field = self.__layout[key]
            shape = field.shape
            value = self.__value[field.offset:field.offset + field.width]
        if isinstance(shape, _AggregateMeta):
            return shape(value)
        if isinstance(shape, Layout):
            return View(shape, value)
        if Shape.cast(shape).signed:
            return value.as_signed()
        else:
            return value

    def __getattr__(self, name):
        try:
            item = self[name]
        except KeyError:
            raise AttributeError("View of {!r} does not have a field {!r}; "
                                 "did you mean one of: {}?"
                                 .format(self.__value, name,
                                         ", ".join(repr(name)
                                                   for name, field in self.__layout)))
        if name.startswith("_"):
            raise AttributeError("View of {!r} field {!r} has a reserved name and may only be "
                                 "accessed by indexing"
                                 .format(self.__value, name))
        return item


class _AggregateMeta(ShapeCastable, type):
    def __new__(metacls, name, bases, namespace, *, _layout_cls=None, **kwargs):
        cls = type.__new__(metacls, name, bases, namespace, **kwargs)
        if _layout_cls is not None:
            cls.__layout_cls = _layout_cls
        if "__annotations__" in namespace:
            cls.__layout = cls.__layout_cls(namespace["__annotations__"])
        return cls

    def as_shape(cls):
        return cls.__layout


class _Aggregate(View, metaclass=_AggregateMeta):
    def __init__(self, value=None, *, src_loc_at=0):
        super().__init__(self.__class__, value, src_loc_at=src_loc_at + 1)


class Struct(_Aggregate, _layout_cls=StructLayout):
    pass


class Union(_Aggregate, _layout_cls=UnionLayout):
    pass
