from __future__ import annotations

import builtins
import copy
import math
from collections import defaultdict
from copy import copy, deepcopy
from dataclasses import dataclass
from enum import IntEnum
from typing import Union, TypeVar, TYPE_CHECKING, Optional

import casadi as ca
import numpy as np

if TYPE_CHECKING:
    from ..world_entity import Body

builtin_max = builtins.max
builtin_min = builtins.min
builtin_abs = builtins.abs

_EPS = np.finfo(float).eps * 4.0
pi = ca.pi


@dataclass
class ReferenceFrameMixin:
    reference_frame: Optional[Body]


class StackedCompiledFunction:
    def __init__(self, expressions, parameters=None, additional_views=None):
        combined_expression = vstack(expressions)
        self.compiled_f = combined_expression.compile(parameters=parameters)
        self.symbol_parameters = self.compiled_f.symbol_parameters
        slices = []
        start = 0
        for expression in expressions[:-1]:
            end = start + expression.shape[0]
            slices.append(end)
            start = end
        self.split_out_view = np.split(self.compiled_f.out, slices)
        if additional_views is not None:
            for expression_slice in additional_views:
                self.split_out_view.append(self.compiled_f.out[expression_slice])

    def fast_call(self, *args):
        self.compiled_f.fast_call(*args)
        return self.split_out_view


class CompiledFunction:
    def __init__(self, expression, parameters=None, sparse=False):
        from scipy import sparse as sp

        self.sparse = sparse
        if parameters is None:
            parameters = expression.free_symbols()
        if parameters and not isinstance(parameters[0], list):
            parameters = [parameters]

        self.symbol_parameters = parameters

        if len(parameters) > 0:
            parameters = [Expression(p).s for p in parameters]

        if len(expression) == 0:
            if self.sparse:
                result = sp.csc_matrix(np.empty(expression.shape))
                self.__call__ = lambda **kwargs: result
                self.fast_call = lambda *args: result
                return
        if self.sparse:
            expression.s = ca.sparsify(expression.s)
            try:
                self.compiled_casadi_function = ca.Function('f', parameters, [expression.s])
            except Exception:
                self.compiled_casadi_function = ca.Function('f', parameters, expression.s)
            self.function_buffer, self.function_evaluator = self.compiled_casadi_function.buffer()
            self.csc_indices, self.csc_indptr = expression.s.sparsity().get_ccs()
            self.out = sp.csc_matrix((np.zeros(expression.s.nnz()), self.csc_indptr, self.csc_indices),
                                     shape=expression.shape)
            self.function_buffer.set_res(0, memoryview(self.out.data))
        else:
            try:
                self.compiled_casadi_function = ca.Function('f', parameters, [ca.densify(expression.s)])
            except Exception as e:
                self.compiled_casadi_function = ca.Function('f', parameters, ca.densify(expression.s))
            self.function_buffer, self.function_evaluator = self.compiled_casadi_function.buffer()
            if expression.shape[1] <= 1:
                shape = expression.shape[0]
            else:
                shape = expression.shape
            self.out = np.zeros(shape, order='F')
            self.function_buffer.set_res(0, memoryview(self.out))
        if len(self.symbol_parameters) == 0:
            self.function_evaluator()
            if self.sparse:
                result = self.out.toarray()
            else:
                result = self.out
            self.__call__ = lambda **kwargs: result
            self.fast_call = lambda *args: result

    def __call__(self, **kwargs):
        args = []
        for params in self.symbol_parameters:
            for param in params:
                args.append(kwargs[str(param)])
        filtered_args = np.array(args, dtype=float)
        return self.fast_call(filtered_args)

    def fast_call(self, *args):
        """
        :param args: parameter values in the same order as was used during the creation
        """
        for arg_idx, arg in enumerate(args):
            self.function_buffer.set_arg(arg_idx, memoryview(arg))
        self.function_evaluator()
        return self.out


def _operation_type_error(arg1, operation, arg2):
    return TypeError(f'unsupported operand type(s) for {operation}: \'{arg1.__class__.__name__}\' '
                     f'and \'{arg2.__class__.__name__}\'')


class Symbol_:

    def __str__(self):
        return str(self.s)

    def pretty_str(self):
        return to_str(self)

    def __repr__(self):
        return repr(self.s)

    def __hash__(self):
        return self.s.__hash__()

    def __getitem__(self, item):
        if isinstance(item, np.ndarray) and item.dtype == bool:
            item = (np.where(item)[0], slice(None, None))
        return Expression(self.s[item])

    def __setitem__(self, key, value):
        try:
            value = value.s
        except AttributeError:
            pass
        self.s[key] = value

    @property
    def shape(self):
        return self.s.shape

    def __len__(self):
        return self.shape[0]

    def free_symbols(self):
        return free_symbols(self.s)

    def to_np(self):
        if not hasattr(self, 'np_data'):
            if self.shape[0] == self.shape[1] == 0:
                self.np_data = np.eye(0)
            elif self.s.shape[0] * self.s.shape[1] <= 1:
                self.np_data = float(ca.evalf(self.s))
            elif self.s.shape[0] == 1 or self.s.shape[1] == 1:
                self.np_data = np.array(ca.evalf(self.s)).ravel()
            else:
                self.np_data = np.array(ca.evalf(self.s))
        return self.np_data

    def compile(self, parameters=None, sparse=False):
        return CompiledFunction(self, parameters, sparse)


class Symbol(Symbol_):
    _registry = {}

    def __new__(cls, name: str):
        """
        Multiton design pattern prevents two symbol instances with the same name.
        """
        if name in cls._registry:
            return cls._registry[name]
        instance = super().__new__(cls)
        instance.s = ca.SX.sym(name)
        instance.name = name
        cls._registry[name] = instance
        return instance

    def __add__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__add__(other))
        if isinstance(other, Symbol_):
            sum_ = self.s.__add__(other.s)
            if isinstance(other, (Symbol, Expression)):
                return Expression(sum_)
            elif isinstance(other, Vector3):
                return Vector3(sum_)
            elif isinstance(other, Point3):
                return Point3(sum_)
        raise _operation_type_error(self, '+', other)

    def __radd__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__radd__(other))
        raise _operation_type_error(other, '+', self)

    def __sub__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__sub__(other))
        if isinstance(other, Symbol_):
            result = self.s.__sub__(other.s)
            if isinstance(other, (Symbol, Expression)):
                return Expression(result)
            elif isinstance(other, Vector3):
                return Vector3(result)
            elif isinstance(other, Point3):
                return Point3(result)
        raise _operation_type_error(self, '-', other)

    def __rsub__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__rsub__(other))
        raise _operation_type_error(other, '-', self)

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__mul__(other))
        if isinstance(other, Symbol_):
            result = self.s.__mul__(other.s)
            if isinstance(other, (Symbol, Expression)):
                return Expression(result)
            elif isinstance(other, Vector3):
                return Vector3(result)
            elif isinstance(other, Point3):
                return Point3(result)
        raise _operation_type_error(self, '*', other)

    def __rmul__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__rmul__(other))
        raise _operation_type_error(other, '*', self)

    def __truediv__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__truediv__(other))
        if isinstance(other, Symbol_):
            result = self.s.__truediv__(other.s)
            if isinstance(other, (Symbol, Expression)):
                return Expression(result)
            elif isinstance(other, Vector3):
                return Vector3(result)
            elif isinstance(other, Point3):
                return Point3(result)
        raise _operation_type_error(self, '/', other)

    def __rtruediv__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__rtruediv__(other))
        raise _operation_type_error(other, '/', self)

    def __floordiv__(self, other):
        return floor(self / other)

    def __mod__(self, other):
        return fmod(self, other)

    def __divmod__(self, other):
        return self // other, self % other

    def __rfloordiv__(self, other):
        return floor(other / self)

    def __rmod__(self, other):
        return fmod(other, self)

    def __rdivmod__(self, other):
        return other // self, other % self

    def __lt__(self, other):
        if isinstance(other, Symbol_):
            other = other.s
        return Expression(self.s.__lt__(other))

    def __le__(self, other):
        if isinstance(other, Symbol_):
            other = other.s
        return Expression(self.s.__le__(other))

    def __gt__(self, other):
        if isinstance(other, Symbol_):
            other = other.s
        return Expression(self.s.__gt__(other))

    def __ge__(self, other):
        if isinstance(other, Symbol_):
            other = other.s
        return Expression(self.s.__ge__(other))

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __ne__(self, other):
        return hash(self) != hash(other)

    def __neg__(self):
        return Expression(self.s.__neg__())

    def __invert__(self):
        return logic_not(self)

    def __or__(self, other):
        return logic_or(self, other)

    def __and__(self, other):
        return logic_and(self, other)

    def __pow__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__pow__(other))
        if isinstance(other, Symbol_):
            result = self.s.__pow__(other.s)
            if isinstance(other, (Symbol, Expression)):
                return Expression(result)
            elif isinstance(other, Vector3):
                return Vector3(result)
            elif isinstance(other, Point3):
                return Point3(result)
        raise _operation_type_error(self, '**', other)

    def __rpow__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__rpow__(other))
        raise _operation_type_error(other, '**', self)

    def __hash__(self):
        return hash(self.name)


class Expression(Symbol_):

    def __init__(self, data=None):
        if data is None:
            data = []
        if isinstance(data, ca.SX):
            self.s = data
        elif isinstance(data, Symbol_):
            self.s = data.s
        elif isinstance(data, (int, float, np.ndarray)):
            self.s = ca.SX(data)
        else:
            x = len(data)
            if x == 0:
                self.s = ca.SX()
                return
            if isinstance(data[0], list) or isinstance(data[0], tuple) or isinstance(data[0], np.ndarray):
                y = len(data[0])
            else:
                y = 1
            self.s = ca.SX(x, y)
            for i in range(self.shape[0]):
                if y > 1:
                    for j in range(self.shape[1]):
                        self[i, j] = data[i][j]
                else:
                    if isinstance(data[i], Symbol):
                        self[i] = data[i].s
                    else:
                        self[i] = data[i]

    def remove(self, rows, columns):
        self.s.remove(rows, columns)

    def split(self):
        assert self.shape[0] == 1 and self.shape[1] == 1
        parts = [Expression(self.s.dep(i)) for i in range(self.s.n_dep())]
        return parts

    def __copy__(self):
        return Expression(copy(self.s))

    def __add__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__add__(other))
        if isinstance(other, Point3):
            return Point3(self.s.__add__(other.s))
        if isinstance(other, Vector3):
            return Vector3(self.s.__add__(other.s))
        if isinstance(other, (Expression, Symbol)):
            return Expression(self.s.__add__(other.s))
        raise _operation_type_error(self, '+', other)

    def __radd__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__radd__(other))
        raise _operation_type_error(other, '+', self)

    def __sub__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__sub__(other))
        if isinstance(other, Point3):
            return Point3(self.s.__sub__(other.s))
        if isinstance(other, Vector3):
            return Vector3(self.s.__sub__(other.s))
        if isinstance(other, (Expression, Symbol)):
            return Expression(self.s.__sub__(other.s))
        raise _operation_type_error(self, '-', other)

    def __rsub__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__rsub__(other))
        raise _operation_type_error(other, '-', self)

    def __truediv__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__truediv__(other))
        if isinstance(other, Point3):
            return Point3(self.s.__truediv__(other.s))
        if isinstance(other, Vector3):
            return Vector3(self.s.__truediv__(other.s))
        if isinstance(other, (Expression, Symbol)):
            return Expression(self.s.__truediv__(other.s))
        raise _operation_type_error(self, '/', other)

    def __rtruediv__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__rtruediv__(other))
        raise _operation_type_error(other, '/', self)

    def __floordiv__(self, other):
        return floor(self / other)

    def __mod__(self, other):
        return fmod(self, other)

    def __divmod__(self, other):
        return self // other, self % other

    def __rfloordiv__(self, other):
        return floor(other / self)

    def __rmod__(self, other):
        return fmod(other, self)

    def __rdivmod__(self, other):
        return other // self, other % self

    def __abs__(self):
        return abs(self)

    def __floor__(self):
        return floor(self)

    def __ceil__(self):
        return ceil(self)

    def __ge__(self, other):
        return greater_equal(self, other)

    def __gt__(self, other):
        return greater(self, other)

    def __le__(self, other):
        return less_equal(self, other)

    def __lt__(self, other):
        return less(self, other)

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__mul__(other))
        if isinstance(other, Point3):
            return Point3(self.s.__mul__(other.s))
        if isinstance(other, Vector3):
            return Vector3(self.s.__mul__(other.s))
        if isinstance(other, (Expression, Symbol)):
            return Expression(self.s.__mul__(other.s))
        raise _operation_type_error(self, '*', other)

    def __rmul__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__rmul__(other))
        raise _operation_type_error(other, '*', self)

    def __neg__(self):
        return Expression(self.s.__neg__())

    def __invert__(self):
        return logic_not(self)

    def __pow__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__pow__(other))
        if isinstance(other, (Expression, Symbol)):
            return Expression(self.s.__pow__(other.s))
        if isinstance(other, (Vector3)):
            return Vector3(self.s.__pow__(other.s))
        if isinstance(other, (Point3)):
            return Point3(self.s.__pow__(other.s))
        raise _operation_type_error(self, '**', other)

    def __rpow__(self, other):
        if isinstance(other, (int, float)):
            return Expression(self.s.__rpow__(other))
        raise _operation_type_error(other, '**', self)

    def __eq__(self, other):
        if isinstance(other, Symbol_):
            other = other.s
        return Expression(self.s.__eq__(other))

    def __or__(self, other):
        return logic_or(self, other)

    def __and__(self, other):
        return logic_and(self, other)

    def __ne__(self, other):
        if isinstance(other, Symbol_):
            other = other.s
        return Expression(self.s.__ne__(other))

    def dot(self, other):
        if isinstance(other, Expression):
            if self.shape[1] == 1 and other.shape[1] == 1:
                return Expression(ca.mtimes(self.T.s, other.s))
            return Expression(ca.mtimes(self.s, other.s))
        raise _operation_type_error(self, 'dot', other)

    @property
    def T(self):
        return Expression(self.s.T)

    def reshape(self, new_shape):
        return Expression(self.s.reshape(new_shape))


TrinaryFalse = 0
TrinaryUnknown = 0.5
TrinaryTrue = 1

BinaryTrue = Expression(True)
BinaryFalse = Expression(False)


class TransformationMatrix(Symbol_, ReferenceFrameMixin):

    def __init__(self, data=None, reference_frame=None, child_frame=None, sanity_check=True):
        self.reference_frame = reference_frame
        self.child_frame = child_frame
        if data is None:
            self.s = ca.SX.eye(4)
            return
        elif isinstance(data, ca.SX):
            self.s = data
        elif isinstance(data, (Expression, RotationMatrix, TransformationMatrix)):
            self.s = data.s
            if isinstance(data, RotationMatrix):
                self.reference_frame = self.reference_frame or data.reference_frame
            if isinstance(data, TransformationMatrix):
                self.child_frame = self.child_frame or data.child_frame
        else:
            self.s = Expression(data).s
        if sanity_check:
            if self.shape[0] != 4 or self.shape[1] != 4:
                raise ValueError(f'{self.__class__.__name__} can only be initialized with 4x4 shaped data.')
            self[3, 0] = 0
            self[3, 1] = 0
            self[3, 2] = 0
            self[3, 3] = 1

    @property
    def x(self):
        return self[0, 3]

    @x.setter
    def x(self, value):
        self[0, 3] = value

    @property
    def y(self):
        return self[1, 3]

    @y.setter
    def y(self, value):
        self[1, 3] = value

    @property
    def z(self):
        return self[2, 3]

    @z.setter
    def z(self, value):
        self[2, 3] = value

    @classmethod
    def from_point_rotation_matrix(cls, point=None, rotation_matrix=None, reference_frame=None, child_frame=None):
        if rotation_matrix is None:
            a_T_b = cls(reference_frame=reference_frame, child_frame=child_frame)
        else:
            a_T_b = cls(rotation_matrix, reference_frame=reference_frame, child_frame=child_frame, sanity_check=False)
        if point is not None:
            a_T_b[0, 3] = point.x
            a_T_b[1, 3] = point.y
            a_T_b[2, 3] = point.z
        return a_T_b

    def dot(self, other):
        if isinstance(other, (Vector3, Point3, RotationMatrix, TransformationMatrix)):
            result = ca.mtimes(self.s, other.s)
            if isinstance(other, Vector3):
                result = Vector3(result, reference_frame=self.reference_frame)
                return result
            if isinstance(other, Point3):
                result = Point3(result, reference_frame=self.reference_frame)
                return result
            if isinstance(other, RotationMatrix):
                result = RotationMatrix(result, reference_frame=self.reference_frame, sanity_check=False)
                return result
            if isinstance(other, TransformationMatrix):
                result = TransformationMatrix(result, reference_frame=self.reference_frame,
                                              child_frame=other.child_frame,
                                              sanity_check=False)
                return result
        raise _operation_type_error(self, 'dot', other)

    def __matmul__(self, other):
        return self.dot(other)

    def __rmatmul__(self, other):
        return other.dot(self)

    def inverse(self):
        inv = TransformationMatrix(child_frame=self.reference_frame, reference_frame=self.child_frame)
        inv[:3, :3] = self[:3, :3].T
        inv[:3, 3] = dot(-inv[:3, :3], self[:3, 3])
        return inv

    @classmethod
    def from_xyz_rpy(cls, x=None, y=None, z=None, roll=None, pitch=None, yaw=None, reference_frame=None,
                     child_frame=None):
        p = Point3.from_xyz(x, y, z)
        r = RotationMatrix.from_rpy(roll, pitch, yaw)
        return cls.from_point_rotation_matrix(p, r, reference_frame=reference_frame, child_frame=child_frame)

    @classmethod
    def from_xyz_quat(cls, pos_x=None, pos_y=None, pos_z=None, quat_w=None, quat_x=None, quat_y=None, quat_z=None,
                      reference_frame=None, child_frame=None):
        p = Point3.from_xyz(pos_x, pos_y, pos_z)
        r = RotationMatrix.from_quaternion(q=Quaternion.from_xyzw(w=quat_w, x=quat_x, y=quat_y, z=quat_z))
        return cls.from_point_rotation_matrix(p, r, reference_frame=reference_frame, child_frame=child_frame)

    def to_position(self):
        result = Point3(self[:4, 3:], reference_frame=self.reference_frame)
        return result

    def to_translation(self):
        """
        :return: sets the rotation part of a frame to identity
        """
        r = TransformationMatrix()
        r[0, 3] = self[0, 3]
        r[1, 3] = self[1, 3]
        r[2, 3] = self[2, 3]
        return TransformationMatrix(r, reference_frame=self.reference_frame, child_frame=None)

    def to_rotation(self):
        return RotationMatrix(self)

    def to_quaternion(self):
        return Quaternion.from_rotation_matrix(self)

    def __deepcopy__(self, memo) -> TransformationMatrix:
        """
        Even in a deep copy, we don't want to copy the reference and child frame, just the matrix itself.
        """
        if id(self) in memo:
            return memo[id(self)]
        return TransformationMatrix(deepcopy(self.s),
                                    reference_frame=self.reference_frame,
                                    child_frame=self.child_frame)


class RotationMatrix(Symbol_, ReferenceFrameMixin):

    def __init__(self, data=None, reference_frame=None, child_frame=None, sanity_check=True):
        self.reference_frame = reference_frame
        self.child_frame = child_frame
        if isinstance(data, ca.SX):
            self.s = data
        elif isinstance(data, Quaternion):
            self.s = self.__quaternion_to_rotation_matrix(data).s
            self.reference_frame = self.reference_frame or data.reference_frame
        elif isinstance(data, (RotationMatrix, TransformationMatrix)):
            self.s = copy(data.s)
            self.reference_frame = data.reference_frame
            self.child_frame = child_frame
        elif data is None:
            self.s = ca.SX.eye(4)
            return
        else:
            self.s = Expression(data).s
        if sanity_check:
            if self.shape[0] != 4 or self.shape[1] != 4:
                raise ValueError(f'{self.__class__.__name__} can only be initialized with 4x4 shaped data, '
                                 f'you have{self.shape}.')
            self[0, 3] = 0
            self[1, 3] = 0
            self[2, 3] = 0
            self[3, 0] = 0
            self[3, 1] = 0
            self[3, 2] = 0
            self[3, 3] = 1

    @classmethod
    def from_axis_angle(cls, axis, angle, reference_frame=None):
        """
        Conversion of unit axis and angle to 4x4 rotation matrix according to:
        https://www.euclideanspace.com/maths/geometry/rotations/conversions/angleToMatrix/index.htm
        """
        # use casadi to prevent a bunch of Expression.__init__.py calls
        axis = axis.s
        try:
            angle = angle.s
        except AttributeError:
            pass
        ct = ca.cos(angle)
        st = ca.sin(angle)
        vt = 1 - ct
        m_vt = axis * vt
        m_st = axis * st
        m_vt_0_ax = (m_vt[0] * axis)[1:]
        m_vt_1_2 = m_vt[1] * axis[2]
        s = ca.SX.eye(4)
        ct__m_vt__axis = ct + m_vt * axis
        s[0, 0] = ct__m_vt__axis[0]
        s[0, 1] = -m_st[2] + m_vt_0_ax[0]
        s[0, 2] = m_st[1] + m_vt_0_ax[1]
        s[1, 0] = m_st[2] + m_vt_0_ax[0]
        s[1, 1] = ct__m_vt__axis[1]
        s[1, 2] = -m_st[0] + m_vt_1_2
        s[2, 0] = -m_st[1] + m_vt_0_ax[1]
        s[2, 1] = m_st[0] + m_vt_1_2
        s[2, 2] = ct__m_vt__axis[2]
        return cls(s, reference_frame=reference_frame, sanity_check=False)

    @classmethod
    def __quaternion_to_rotation_matrix(cls, q):
        """
        Unit quaternion to 4x4 rotation matrix according to:
        https://github.com/orocos/orocos_kinematics_dynamics/blob/master/orocos_kdl/src/frames.cpp#L167
        """
        x = q[0]
        y = q[1]
        z = q[2]
        w = q[3]
        x2 = x * x
        y2 = y * y
        z2 = z * z
        w2 = w * w
        return cls([[w2 + x2 - y2 - z2, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y, 0],
                    [2 * x * y + 2 * w * z, w2 - x2 + y2 - z2, 2 * y * z - 2 * w * x, 0],
                    [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, w2 - x2 - y2 + z2, 0],
                    [0, 0, 0, 1]],
                   reference_frame=q.reference_frame)

    @classmethod
    def from_quaternion(cls, q):
        return cls.__quaternion_to_rotation_matrix(q)

    def x_vector(self):
        return Vector3(self[:4, 3:], reference_frame=self.reference_frame)

    def y_vector(self):
        return Vector3(self[:4, 3:], reference_frame=self.reference_frame)

    def z_vector(self):
        return Vector3(self[:4, 3:], reference_frame=self.reference_frame)

    def dot(self, other):
        if isinstance(other, (Vector3, Point3, RotationMatrix, TransformationMatrix)):
            result = ca.mtimes(self.s, other.s)
            if isinstance(other, Vector3):
                result = Vector3(result)
            elif isinstance(other, Point3):
                result = Point3(result)
            elif isinstance(other, RotationMatrix):
                result = RotationMatrix(result, sanity_check=False)
            elif isinstance(other, TransformationMatrix):
                result = TransformationMatrix(result, sanity_check=False)
            result.reference_frame = self.reference_frame
            return result
        raise _operation_type_error(self, 'dot', other)

    def __matmul__(self, other):
        return self.dot(other)

    def __rmatmul__(self, other):
        return other.dot(self)

    def to_axis_angle(self):
        return self.to_quaternion().to_axis_angle()

    def to_angle(self, hint=None):
        """
        :param hint: A function whose sign of the result will be used to determine if angle should be positive or
                        negative
        :return:
        """
        axis, angle = self.to_axis_angle()
        if hint is not None:
            return normalize_angle(if_greater_zero(hint(axis),
                                                   if_result=angle,
                                                   else_result=-angle))
        else:
            return angle

    @classmethod
    def from_vectors(cls, x=None, y=None, z=None, reference_frame=None):
        if x is not None:
            x.scale(1)
        if y is not None:
            y.scale(1)
        if z is not None:
            z.scale(1)
        if x is not None and y is not None and z is None:
            z = cross(x, y)
            z.scale(1)
        elif x is not None and y is None and z is not None:
            y = cross(z, x)
            y.scale(1)
        elif x is None and y is not None and z is not None:
            x = cross(y, z)
            x.scale(1)
        # else:
        #     raise AttributeError(f'only one vector can be None')
        R = cls([[x[0], y[0], z[0], 0],
                 [x[1], y[1], z[1], 0],
                 [x[2], y[2], z[2], 0],
                 [0, 0, 0, 1]],
                reference_frame=reference_frame)
        R.normalize()
        return R

    @classmethod
    def from_rpy(cls, roll=None, pitch=None, yaw=None, reference_frame=None):
        """
        Conversion of roll, pitch, yaw to 4x4 rotation matrix according to:
        https://github.com/orocos/orocos_kinematics_dynamics/blob/master/orocos_kdl/src/frames.cpp#L167
        """
        roll = 0 if roll is None else roll
        pitch = 0 if pitch is None else pitch
        yaw = 0 if yaw is None else yaw
        try:
            roll = roll.s
        except AttributeError:
            pass
        try:
            pitch = pitch.s
        except AttributeError:
            pass
        try:
            yaw = yaw.s
        except AttributeError:
            pass
        s = ca.SX.eye(4)

        s[0, 0] = ca.cos(yaw) * ca.cos(pitch)
        s[0, 1] = (ca.cos(yaw) * ca.sin(pitch) * ca.sin(roll)) - (ca.sin(yaw) * ca.cos(roll))
        s[0, 2] = (ca.sin(yaw) * ca.sin(roll)) + (ca.cos(yaw) * ca.sin(pitch) * ca.cos(roll))
        s[1, 0] = ca.sin(yaw) * ca.cos(pitch)
        s[1, 1] = (ca.cos(yaw) * ca.cos(roll)) + (ca.sin(yaw) * ca.sin(pitch) * ca.sin(roll))
        s[1, 2] = (ca.sin(yaw) * ca.sin(pitch) * ca.cos(roll)) - (ca.cos(yaw) * ca.sin(roll))
        s[2, 0] = -ca.sin(pitch)
        s[2, 1] = ca.cos(pitch) * ca.sin(roll)
        s[2, 2] = ca.cos(pitch) * ca.cos(roll)
        return cls(s, reference_frame=reference_frame, sanity_check=False)

    def inverse(self):
        return self.T

    def to_rpy(self):
        """
        :return: roll, pitch, yaw
        """
        i = 0
        j = 1
        k = 2

        cy = sqrt(self[i, i] * self[i, i] + self[j, i] * self[j, i])
        if0 = cy - _EPS
        ax = if_greater_zero(if0,
                             atan2(self[k, j], self[k, k]),
                             atan2(-self[j, k], self[j, j]))
        ay = if_greater_zero(if0,
                             atan2(-self[k, i], cy),
                             atan2(-self[k, i], cy))
        az = if_greater_zero(if0,
                             atan2(self[j, i], self[i, i]),
                             0)
        return ax, ay, az

    def to_quaternion(self):
        return Quaternion.from_rotation_matrix(self)

    def normalize(self):
        """Scales each of the axes to the length of one."""
        scale_v = 1.0
        self[:3, 0] = scale(self[:3, 0], scale_v)
        self[:3, 1] = scale(self[:3, 1], scale_v)
        self[:3, 2] = scale(self[:3, 2], scale_v)

    @property
    def T(self):
        return RotationMatrix(self.s.T, reference_frame=self.reference_frame)


class Point3(Symbol_, ReferenceFrameMixin):

    def __init__(self, data=None, reference_frame=None):
        self.reference_frame = reference_frame
        if data is None:
            self.s = ca.SX([0, 0, 0, 1])
            return
        if isinstance(data, (Point3, Vector3)):
            self.reference_frame = self.reference_frame or data.reference_frame
            self.s = ca.SX([0, 0, 0, 1])
            self.s[0] = data.x.s
            self.s[1] = data.y.s
            self.s[2] = data.z.s
        else:
            self.s = ca.SX([0, 0, 0, 1])
            self[0] = data[0]
            self[1] = data[1]
            self[2] = data[2]

    @classmethod
    def from_xyz(cls, x=None, y=None, z=None, reference_frame=None):
        x = 0 if x is None else x
        y = 0 if y is None else y
        z = 0 if z is None else z
        return cls((x, y, z), reference_frame=reference_frame)

    def norm(self):
        return norm(self)

    @property
    def x(self):
        return self[0]

    @x.setter
    def x(self, value):
        self[0] = value

    @property
    def y(self):
        return self[1]

    @y.setter
    def y(self, value):
        self[1] = value

    @property
    def z(self):
        return self[2]

    @z.setter
    def z(self, value):
        self[2] = value

    def __add__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__add__(other))
        elif isinstance(other, (Vector3, Expression, Symbol)):
            result = Point3(self.s.__add__(other.s))
        else:
            raise _operation_type_error(self, '+', other)
        result.reference_frame = self.reference_frame
        return result

    def __radd__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__add__(other))
        else:
            raise _operation_type_error(other, '+', self)
        result.reference_frame = self.reference_frame
        return result

    def __sub__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__sub__(other))
        elif isinstance(other, Point3):
            result = Vector3(self.s.__sub__(other.s))
        elif isinstance(other, (Symbol, Expression, Vector3)):
            result = Point3(self.s.__sub__(other.s))
        else:
            raise _operation_type_error(self, '-', other)
        result.reference_frame = self.reference_frame
        return result

    def __rsub__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__rsub__(other))
        else:
            raise _operation_type_error(other, '-', self)
        result.reference_frame = self.reference_frame
        return result

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__mul__(other))
        elif isinstance(other, (Symbol, Expression)):
            result = Point3(self.s.__mul__(other.s))
        else:
            raise _operation_type_error(self, '*', other)
        result.reference_frame = self.reference_frame
        return result

    def __rmul__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__mul__(other))
        else:
            raise _operation_type_error(other, '*', self)
        result.reference_frame = self.reference_frame
        return result

    def __truediv__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__truediv__(other))
        elif isinstance(other, (Symbol, Expression)):
            result = Point3(self.s.__truediv__(other.s))
        else:
            raise _operation_type_error(self, '/', other)
        result.reference_frame = self.reference_frame
        return result

    def __rtruediv__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__rtruediv__(other))
        else:
            raise _operation_type_error(other, '/', self)
        result.reference_frame = self.reference_frame
        return result

    def __neg__(self) -> Point3:
        result = Point3(self.s.__neg__())
        result.reference_frame = self.reference_frame
        return result

    def __pow__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__pow__(other))
        elif isinstance(other, (Symbol, Expression)):
            result = Point3(self.s.__pow__(other.s))
        else:
            raise _operation_type_error(self, '**', other)
        result.reference_frame = self.reference_frame
        return result

    def __rpow__(self, other):
        if isinstance(other, (int, float)):
            result = Point3(self.s.__rpow__(other))
        else:
            raise _operation_type_error(other, '**', self)
        result.reference_frame = self.reference_frame
        return result

    def dot(self, other):
        if isinstance(other, (Point3, Vector3)):
            return Expression(ca.mtimes(self[:3].T.s, other[:3].s))
        raise _operation_type_error(self, 'dot', other)


class Vector3(Symbol_, ReferenceFrameMixin):

    def __init__(self, data=None, reference_frame=None):
        point = Point3(data, reference_frame=reference_frame)
        self.s = point.s
        self.reference_frame = point.reference_frame
        self.vis_frame = self.reference_frame
        self[3] = 0

    @classmethod
    def from_xyz(cls, x=None, y=None, z=None, reference_frame=None):
        x = 0 if x is None else x
        y = 0 if y is None else y
        z = 0 if z is None else z
        return cls((x, y, z), reference_frame=reference_frame)

    @property
    def x(self):
        return self[0]

    @x.setter
    def x(self, value):
        self[0] = value

    @property
    def y(self):
        return self[1]

    @y.setter
    def y(self, value):
        self[1] = value

    @property
    def z(self):
        return self[2]

    @z.setter
    def z(self, value):
        self[2] = value

    def __add__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__add__(other))
        elif isinstance(other, Point3):
            result = Point3(self.s.__add__(other.s))
        elif isinstance(other, (Vector3, Expression, Symbol)):
            result = Vector3(self.s.__add__(other.s))
        else:
            raise _operation_type_error(self, '+', other)
        result.reference_frame = self.reference_frame
        return result

    def __radd__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__add__(other))
        else:
            raise _operation_type_error(other, '+', self)
        result.reference_frame = self.reference_frame
        return result

    def __sub__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__sub__(other))
        elif isinstance(other, Point3):
            result = Point3(self.s.__sub__(other.s))
        elif isinstance(other, (Symbol, Expression, Vector3)):
            result = Vector3(self.s.__sub__(other.s))
        else:
            raise _operation_type_error(self, '-', other)
        result.reference_frame = self.reference_frame
        return result

    def __rsub__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__rsub__(other))
        else:
            raise _operation_type_error(other, '-', self)
        result.reference_frame = self.reference_frame
        return result

    def __mul__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__mul__(other))
        elif isinstance(other, (Symbol, Expression)):
            result = Vector3(self.s.__mul__(other.s))
        else:
            raise _operation_type_error(self, '*', other)
        result.reference_frame = self.reference_frame
        return result

    def __rmul__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__mul__(other))
        else:
            raise _operation_type_error(other, '*', self)
        result.reference_frame = self.reference_frame
        return result

    def __pow__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__pow__(other))
        elif isinstance(other, (Symbol, Expression)):
            result = Vector3(self.s.__pow__(other.s))
        else:
            raise _operation_type_error(self, '**', other)
        result.reference_frame = self.reference_frame
        return result

    def __rpow__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__rpow__(other))
        else:
            raise _operation_type_error(other, '**', self)
        result.reference_frame = self.reference_frame
        return result

    def __truediv__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__truediv__(other))
        elif isinstance(other, (Symbol, Expression)):
            result = Vector3(self.s.__truediv__(other.s))
        else:
            raise _operation_type_error(self, '/', other)
        result.reference_frame = self.reference_frame
        return result

    def __rtruediv__(self, other):
        if isinstance(other, (int, float)):
            result = Vector3(self.s.__rtruediv__(other))
        else:
            raise _operation_type_error(other, '/', self)
        result.reference_frame = self.reference_frame
        return result

    def __neg__(self):
        result = Vector3(self.s.__neg__())
        result.reference_frame = self.reference_frame
        return result

    def dot(self, other):
        if isinstance(other, (Point3, Vector3)):
            return Expression(ca.mtimes(self[:3].T.s, other[:3].s))
        raise _operation_type_error(self, 'dot', other)

    def cross(self, other):
        result = ca.cross(self.s[:3], other.s[:3])
        result = Vector3(result)
        result.reference_frame = self.reference_frame
        return result

    def norm(self):
        return norm(self)

    def scale(self, a):
        self.s = (save_division(self, self.norm()) * a).s


class Quaternion(Symbol_, ReferenceFrameMixin):
    def __init__(self, data=None, reference_frame=None):
        self.reference_frame = reference_frame
        if data is None:
            data = (0, 0, 0, 1)
        self.s = ca.SX(4, 1)
        self[0], self[1], self[2], self[3] = data[0], data[1], data[2], data[3]

    def __neg__(self):
        return Quaternion(self.s.__neg__())

    @classmethod
    def from_xyzw(cls, x, y, z, w, reference_frame=None):
        return cls((x, y, z, w), reference_frame=reference_frame)

    @property
    def x(self):
        return self[0]

    @x.setter
    def x(self, value):
        self[0] = value

    @property
    def y(self):
        return self[1]

    @y.setter
    def y(self, value):
        self[1] = value

    @property
    def z(self):
        return self[2]

    @z.setter
    def z(self, value):
        self[2] = value

    @property
    def w(self):
        return self[3]

    @w.setter
    def w(self, value):
        self[3] = value

    @classmethod
    def from_axis_angle(cls, axis, angle, reference_frame=None):
        half_angle = angle / 2
        return cls((axis[0] * sin(half_angle),
                    axis[1] * sin(half_angle),
                    axis[2] * sin(half_angle),
                    cos(half_angle)),
                   reference_frame=reference_frame)

    @classmethod
    def from_rpy(cls, roll, pitch, yaw, reference_frame=None):
        roll = Expression(roll).s
        pitch = Expression(pitch).s
        yaw = Expression(yaw).s
        roll_half = roll / 2.0
        pitch_half = pitch / 2.0
        yaw_half = yaw / 2.0

        c_roll = cos(roll_half)
        s_roll = sin(roll_half)
        c_pitch = cos(pitch_half)
        s_pitch = sin(pitch_half)
        c_yaw = cos(yaw_half)
        s_yaw = sin(yaw_half)

        cc = c_roll * c_yaw
        cs = c_roll * s_yaw
        sc = s_roll * c_yaw
        ss = s_roll * s_yaw

        x = c_pitch * sc - s_pitch * cs
        y = c_pitch * ss + s_pitch * cc
        z = c_pitch * cs - s_pitch * sc
        w = c_pitch * cc + s_pitch * ss

        return cls((x, y, z, w), reference_frame=reference_frame)

    @classmethod
    def from_rotation_matrix(cls, r):
        q = Expression((0, 0, 0, 0))
        t = trace(r)

        if0 = t - r[3, 3]

        if1 = r[1, 1] - r[0, 0]

        m_i_i = if_greater_zero(if1, r[1, 1], r[0, 0])
        m_i_j = if_greater_zero(if1, r[1, 2], r[0, 1])
        m_i_k = if_greater_zero(if1, r[1, 0], r[0, 2])

        m_j_i = if_greater_zero(if1, r[2, 1], r[1, 0])
        m_j_j = if_greater_zero(if1, r[2, 2], r[1, 1])
        m_j_k = if_greater_zero(if1, r[2, 0], r[1, 2])

        m_k_i = if_greater_zero(if1, r[0, 1], r[2, 0])
        m_k_j = if_greater_zero(if1, r[0, 2], r[2, 1])
        m_k_k = if_greater_zero(if1, r[0, 0], r[2, 2])

        if2 = r[2, 2] - m_i_i

        m_i_i = if_greater_zero(if2, r[2, 2], m_i_i)
        m_i_j = if_greater_zero(if2, r[2, 0], m_i_j)
        m_i_k = if_greater_zero(if2, r[2, 1], m_i_k)

        m_j_i = if_greater_zero(if2, r[0, 2], m_j_i)
        m_j_j = if_greater_zero(if2, r[0, 0], m_j_j)
        m_j_k = if_greater_zero(if2, r[0, 1], m_j_k)

        m_k_i = if_greater_zero(if2, r[1, 2], m_k_i)
        m_k_j = if_greater_zero(if2, r[1, 0], m_k_j)
        m_k_k = if_greater_zero(if2, r[1, 1], m_k_k)

        t = if_greater_zero(if0, t, m_i_i - (m_j_j + m_k_k) + r[3, 3])
        q[0] = if_greater_zero(if0, r[2, 1] - r[1, 2],
                               if_greater_zero(if2, m_i_j + m_j_i,
                                               if_greater_zero(if1, m_k_i + m_i_k, t)))
        q[1] = if_greater_zero(if0, r[0, 2] - r[2, 0],
                               if_greater_zero(if2, m_k_i + m_i_k,
                                               if_greater_zero(if1, t, m_i_j + m_j_i)))
        q[2] = if_greater_zero(if0, r[1, 0] - r[0, 1],
                               if_greater_zero(if2, t, if_greater_zero(if1, m_i_j + m_j_i,
                                                                       m_k_i + m_i_k)))
        q[3] = if_greater_zero(if0, t, m_k_j - m_j_k)

        q *= 0.5 / sqrt(t * r[3, 3])
        return cls(q, reference_frame=r.reference_frame)

    def conjugate(self):
        return Quaternion((-self[0], -self[1], -self[2], self[3]))

    def multiply(self, q):
        return Quaternion((self.x * q.w + self.y * q.z - self.z * q.y + self.w * q.x,
                           -self.x * q.z + self.y * q.w + self.z * q.x + self.w * q.y,
                           self.x * q.y - self.y * q.x + self.z * q.w + self.w * q.z,
                           -self.x * q.x - self.y * q.y - self.z * q.z + self.w * q.w),
                          reference_frame=self.reference_frame)

    def diff(self, q):
        """
        :return: quaternion p, such that self*p=q
        """
        return self.conjugate().multiply(q)

    def norm(self):
        return norm(self)

    def normalize(self):
        norm_ = self.norm()
        self.x /= norm_
        self.y /= norm_
        self.z /= norm_
        self.w /= norm_

    def to_axis_angle(self):
        self.normalize()
        w2 = sqrt(1 - self.w ** 2)
        m = if_eq_zero(w2, 1, w2)  # avoid /0
        angle = if_eq_zero(w2, 0, (2 * acos(limit(self.w, -1, 1))))
        x = if_eq_zero(w2, 0, self.x / m)
        y = if_eq_zero(w2, 0, self.y / m)
        z = if_eq_zero(w2, 1, self.z / m)
        return Vector3((x, y, z), reference_frame=self.reference_frame), angle

    def to_rotation_matrix(self):
        return RotationMatrix.from_quaternion(self)

    def to_rpy(self):
        return self.to_rotation_matrix().to_rpy()

    def dot(self, other):
        if isinstance(other, Quaternion):
            return Expression(ca.mtimes(self.s.T, other.s))
        raise _operation_type_error(self, 'dot', other)


all_expressions = Union[Symbol_, Symbol, Expression, Point3, Vector3, RotationMatrix, TransformationMatrix, Quaternion]
all_expressions_float = Union[
    Symbol, Expression, Point3, Vector3, RotationMatrix, TransformationMatrix, float, Quaternion]
symbol_expr_float = Union[Symbol, Expression, float, int, IntEnum]
symbol_expr = Union[Symbol, Expression]
PreservedCasType = TypeVar('PreservedCasType', Point3, Vector3, TransformationMatrix, RotationMatrix, Quaternion,
                           Expression)


def var(variables_names: str):
    """
    :param variables_names: e.g. 'a b c'
    :return: e.g. [Symbol('a'), Symbol('b'), Symbol('c')]
    """
    symbols = []
    for v in variables_names.split(' '):
        symbols.append(Symbol(v))
    return symbols


def diag(args):
    try:
        return Expression(ca.diag(args.s))
    except AttributeError:
        return Expression(ca.diag(Expression(args).s))


def hessian(expression, symbols):
    expressions = _to_sx(expression)
    return Expression(ca.hessian(expressions, Expression(symbols).s)[0])


def jacobian(expressions, symbols):
    expressions = Expression(expressions)
    return Expression(ca.jacobian(expressions.s, Expression(symbols).s))


def jacobian_dot(expressions, symbols, symbols_dot):
    Jd = jacobian(expressions, symbols)
    for i in range(Jd.shape[0]):
        for j in range(Jd.shape[1]):
            Jd[i, j] = total_derivative(Jd[i, j], symbols, symbols_dot)
    return Jd


def jacobian_ddot(expressions, symbols, symbols_dot, symbols_ddot):
    symbols_ddot = Expression(symbols_ddot)
    Jdd = jacobian(expressions, symbols)
    for i in range(Jdd.shape[0]):
        for j in range(Jdd.shape[1]):
            Jdd[i, j] = total_derivative2(Jdd[i, j], symbols, symbols_dot, symbols_ddot)
    return Jdd


def equivalent(expression1, expression2):
    expression1 = Expression(expression1).s
    expression2 = Expression(expression2).s
    return ca.is_equal(ca.simplify(expression1), ca.simplify(expression2), 5)


def free_symbols(expression):
    expression = _to_sx(expression)
    return [Symbol._registry[str(s)] for s in ca.symvar(expression)]


def create_symbols(names):
    if isinstance(names, int):
        names = [f's_{i}' for i in range(names)]
    return [Symbol(x) for x in names]


def compile_and_execute(f, params):
    input_ = []
    symbol_params = []
    symbol_params2 = []

    for i, param in enumerate(params):
        if isinstance(param, list):
            param = np.array(param)
        if isinstance(param, np.ndarray):
            symbol_param = ca.SX.sym('m', *param.shape)
            if len(param.shape) == 2:
                number_of_params = param.shape[0] * param.shape[1]
            else:
                number_of_params = param.shape[0]

            input_.append(param.reshape((number_of_params, 1)))
            symbol_params.append(symbol_param)
            asdf = symbol_param.T.reshape((number_of_params, 1))
            symbol_params2.extend(asdf[k] for k in range(number_of_params))
        else:
            input_.append(np.array([param], ndmin=2))
            symbol_param = ca.SX.sym('s')
            symbol_params.append(symbol_param)
            symbol_params2.append(symbol_param)
    symbol_params = [Expression(x) for x in symbol_params]
    symbol_params2 = [Expression(x) for x in symbol_params2]
    expr = f(*symbol_params)
    assert isinstance(expr, Symbol_)
    fast_f = expr.compile(symbol_params2)
    input_ = np.array(np.concatenate(input_).T[0], dtype=float)
    result = fast_f.fast_call(input_)
    if len(result.shape) == 1:
        if result.shape[0] == 1:
            return result[0]
        return result
    if result.shape[0] * result.shape[1] == 1:
        return result[0][0]
    elif result.shape[1] == 1:
        return result.T[0]
    elif result.shape[0] == 1:
        return result[0]
    else:
        return result


def zeros(rows, columns):
    return Expression(ca.SX.zeros(rows, columns))


def ones(x, y):
    return Expression(ca.SX.ones(x, y))


def tri(dimension):
    return Expression(np.tri(dimension))


def abs(x):
    x = Expression(x).s
    result = ca.fabs(x)
    if isinstance(x, Point3):
        return Point3(result)
    elif isinstance(x, Vector3):
        return Vector3(result)
    return Expression(result)


def max(x, y=None):
    x = Expression(x).s
    y = Expression(y).s
    return Expression(ca.fmax(x, y))


def min(x, y=None):
    x = Expression(x).s
    y = Expression(y).s
    return Expression(ca.fmin(x, y))


def limit(x, lower_limit, upper_limit):
    return Expression(max(lower_limit, min(upper_limit, x)))


def if_else(condition, if_result, else_result):
    condition = Expression(condition).s
    if isinstance(if_result, (float, int)):
        if_result = Expression(if_result)
    if isinstance(else_result, (float, int)):
        else_result = Expression(else_result)
    if isinstance(if_result, (Point3, Vector3, TransformationMatrix, RotationMatrix, Quaternion)):
        assert type(if_result) == type(else_result), \
            f'if_else: result types are not equal {type(if_result)} != {type(else_result)}'
    return_type = type(if_result)
    if return_type in (int, float):
        return_type = Expression
    if return_type == Symbol:
        return_type = Expression
    if_result = Expression(if_result).s
    else_result = Expression(else_result).s
    return return_type(ca.if_else(condition, if_result, else_result))


def equal(x, y):
    if isinstance(x, Symbol_):
        x = x.s
    if isinstance(y, Symbol_):
        y = y.s
    return Expression(ca.eq(x, y))


def not_equal(x, y):
    cas_x = _to_sx(x)
    cas_y = _to_sx(y)
    return Expression(ca.ne(cas_x, cas_y))


def less_equal(x, y):
    if isinstance(x, Symbol_):
        x = x.s
    if isinstance(y, Symbol_):
        y = y.s
    return Expression(ca.le(x, y))


def greater_equal(x, y):
    if isinstance(x, Symbol_):
        x = x.s
    if isinstance(y, Symbol_):
        y = y.s
    return Expression(ca.ge(x, y))


def less(x, y):
    if isinstance(x, Symbol_):
        x = x.s
    if isinstance(y, Symbol_):
        y = y.s
    return Expression(ca.lt(x, y))


def greater(x, y, decimal_places=None):
    if decimal_places is not None:
        x = round_up(x, decimal_places)
        y = round_up(y, decimal_places)
    if isinstance(x, Symbol_):
        x = x.s
    if isinstance(y, Symbol_):
        y = y.s
    return Expression(ca.gt(x, y))


def logic_and(*args):
    assert len(args) >= 2, 'and must be called with at least 2 arguments'
    # if there is any False, return False
    if [x for x in args if is_false_symbol(x)]:
        return BinaryFalse
    # filter all True
    args = [x for x in args if not is_true_symbol(x)]
    if len(args) == 0:
        return BinaryTrue
    if len(args) == 1:
        return args[0]
    if len(args) == 2:
        cas_a = _to_sx(args[0])
        cas_b = _to_sx(args[1])
        return Expression(ca.logic_and(cas_a, cas_b))
    else:
        return Expression(ca.logic_and(args[0].s, logic_and(*args[1:]).s))


def logic_and3(*args):
    assert len(args) >= 2, 'and must be called with at least 2 arguments'
    # if there is any False, return False
    if [x for x in args if is_false_symbol(x)]:
        return TrinaryFalse
    # filter all True
    args = [x for x in args if not is_true_symbol(x)]
    if len(args) == 0:
        return TrinaryTrue
    if len(args) == 1:
        return args[0]
    if len(args) == 2:
        cas_a = _to_sx(args[0])
        cas_b = _to_sx(args[1])
        return min(cas_a, cas_b)
    else:
        return logic_and3(args[0], logic_and3(*args[1:]))


def logic_any(args):
    return Expression(ca.logic_any(args.s))


def logic_all(args):
    return Expression(ca.logic_all(args.s))


def logic_or(*args, simplify=True):
    assert len(args) >= 2, 'and must be called with at least 2 arguments'
    # if there is any True, return True
    if simplify and [x for x in args if is_true_symbol(x)]:
        return BinaryTrue
    # filter all False
    if simplify:
        args = [x for x in args if not is_false_symbol(x)]
    if len(args) == 0:
        return BinaryFalse
    if len(args) == 1:
        return args[0]
    if len(args) == 2:
        return Expression(ca.logic_or(_to_sx(args[0]), _to_sx(args[1])))
    else:
        return Expression(ca.logic_or(_to_sx(args[0]), _to_sx(logic_or(*args[1:], False))))


def logic_or3(a, b):
    cas_a = _to_sx(a)
    cas_b = _to_sx(b)
    return max(cas_a, cas_b)


def logic_not(expr):
    cas_expr = _to_sx(expr)
    return Expression(ca.logic_not(cas_expr))


def logic_not3(expr):
    return Expression(1 - expr)


def if_greater(a, b, if_result, else_result):
    a = Expression(a).s
    b = Expression(b).s
    return if_else(ca.gt(a, b), if_result, else_result)


def if_less(a, b, if_result, else_result):
    a = Expression(a).s
    b = Expression(b).s
    return if_else(ca.lt(a, b), if_result, else_result)


def if_greater_zero(condition, if_result, else_result):
    """
    :return: if_result if condition > 0 else else_result
    """
    condition = Expression(condition).s
    return if_else(ca.gt(condition, 0), if_result, else_result)

    # _condition = sign(condition)  # 1 or -1
    # _if = max(0, _condition) * if_result  # 0 or if_result
    # _else = -min(0, _condition) * else_result  # 0 or else_result
    # return Expression(_if + _else + (1 - abs(_condition)) * else_result)  # if_result or else_result


def if_greater_eq_zero(condition, if_result, else_result):
    """
    :return: if_result if condition >= 0 else else_result
    """
    return if_greater_eq(condition, 0, if_result, else_result)


def if_greater_eq(a, b, if_result, else_result):
    """
    :return: if_result if a >= b else else_result
    """
    a = Expression(a).s
    b = Expression(b).s
    return if_else(ca.ge(a, b), if_result, else_result)


def if_less_eq(a, b, if_result, else_result):
    """
    :return: if_result if a <= b else else_result
    """
    return if_greater_eq(b, a, if_result, else_result)


def if_eq_zero(condition, if_result, else_result):
    """
    :return: if_result if condition == 0 else else_result
    """
    return if_else(condition, else_result, if_result)


def if_eq(a, b, if_result, else_result):
    a = Expression(a).s
    b = Expression(b).s
    return if_else(ca.eq(a, b), if_result, else_result)


def if_eq_cases(a, b_result_cases, else_result):
    """
    if a == b_result_cases[0][0]:
        return b_result_cases[0][1]
    elif a == b_result_cases[1][0]:
        return b_result_cases[1][1]
    ...
    else:
        return else_result
    """
    a = _to_sx(a)
    result = _to_sx(else_result)
    for b, b_result in b_result_cases:
        b = _to_sx(b)
        b_result = _to_sx(b_result)
        result = ca.if_else(ca.eq(a, b), b_result, result)
    return Expression(result)


def if_eq_cases_grouped(a, b_result_cases, else_result):
    """
    a: symbol (hash)
    grouped_cases: list of tuples (hash_list, outcome) where hash_list is a list of hashes mapping to outcome.
    else_result: default outcome if no hash matches.
    """
    groups = defaultdict(list)
    for h, res in b_result_cases:
        groups[res].append(_to_sx(h))
    # Rearrange into (hash_list, result) tuples:
    grouped_cases = [(hash_list, _to_sx(result)) for result, hash_list in groups.items()]
    a = _to_sx(a)
    result = _to_sx(else_result)
    for hash_list, outcome in grouped_cases:
        if len(hash_list) >= 2:
            condition = _to_sx(logic_or(*[ca.eq(a, h) for h in hash_list], False))
        else:
            condition = ca.eq(a, hash_list[0])
        result = ca.if_else(condition, outcome, result)
    return Expression(result)


def if_cases(cases, else_result):
    """
    if cases[0][0]:
        return cases[0][1]
    elif cases[1][0]:
        return cases[1][1]
    ...
    else:
        return else_result
    """
    else_result = _to_sx(else_result)
    result = _to_sx(else_result)
    for i in reversed(range(len(cases))):
        case = _to_sx(cases[i][0])
        case_result = _to_sx(cases[i][1])
        result = ca.if_else(case, case_result, result)
    return Expression(result)


def if_less_eq_cases(a, b_result_cases, else_result):
    """
    This only works if b_result_cases is sorted in ascending order.
    if a <= b_result_cases[0][0]:
        return b_result_cases[0][1]
    elif a <= b_result_cases[1][0]:
        return b_result_cases[1][1]
    ...
    else:
        return else_result
    """
    a = _to_sx(a)
    result = _to_sx(else_result)
    for i in reversed(range(len(b_result_cases))):
        b = _to_sx(b_result_cases[i][0])
        b_result = _to_sx(b_result_cases[i][1])
        result = ca.if_else(ca.le(a, b), b_result, result)
    return Expression(result)


def _to_sx(thing):
    try:
        return thing.s
    except AttributeError:
        return thing


def cross(u, v):
    u = Vector3(u)
    v = Vector3(v)
    return u.cross(v)


def norm(v):
    if isinstance(v, (Point3, Vector3)):
        return Expression(ca.norm_2(v[:3].s))
    v = Expression(v).s
    return Expression(ca.norm_2(v))


def scale(v, a):
    return save_division(v, norm(v)) * a


def dot(e1, e2):
    try:
        return e1.dot(e2)
    except Exception as e:
        raise _operation_type_error(e1, 'dot', e2)


def eye(size):
    return Expression(ca.SX.eye(size))


def kron(m1, m2):
    m1 = Expression(m1).s
    m2 = Expression(m2).s
    return Expression(ca.kron(m1, m2))


def trace(matrix):
    matrix = Expression(matrix).s
    s = 0
    for i in range(matrix.shape[0]):
        s += matrix[i, i]
    return Expression(s)


# def rotation_distance(a_R_b, a_R_c):
#     """
#     :param a_R_b: 4x4 or 3x3 Matrix
#     :param a_R_c: 4x4 or 3x3 Matrix
#     :return: angle of axis angle representation of b_R_c
#     """
#     a_R_b = Expression(a_R_b).s
#     a_R_c = Expression(a_R_c).s
#     difference = dot(a_R_b.T, a_R_c)
#     # return axis_angle_from_matrix(difference)[1]
#     angle = (trace(difference[:3, :3]) - 1) / 2
#     angle = min(angle, 1)
#     angle = max(angle, -1)
#     return acos(angle)


def vstack(list_of_matrices):
    if len(list_of_matrices) == 0:
        return Expression()
    return Expression(ca.vertcat(*[_to_sx(x) for x in list_of_matrices]))


def hstack(list_of_matrices):
    if len(list_of_matrices) == 0:
        return Expression()
    return Expression(ca.horzcat(*[_to_sx(x) for x in list_of_matrices]))


def diag_stack(list_of_matrices):
    num_rows = int(math.fsum(e.shape[0] for e in list_of_matrices))
    num_columns = int(math.fsum(e.shape[1] for e in list_of_matrices))
    combined_matrix = zeros(num_rows, num_columns)
    row_counter = 0
    column_counter = 0
    for matrix in list_of_matrices:
        combined_matrix[row_counter:row_counter + matrix.shape[0],
        column_counter:column_counter + matrix.shape[1]] = matrix
        row_counter += matrix.shape[0]
        column_counter += matrix.shape[1]
    return combined_matrix


def normalize_axis_angle(axis, angle):
    # todo add test
    axis = if_less(angle, 0, -axis, axis)
    angle = abs(angle)
    return axis, angle


def axis_angle_from_rpy(roll, pitch, yaw):
    return Quaternion.from_rpy(roll, pitch, yaw).to_axis_angle()


def cosine_distance(v0, v1):
    """
    cosine distance ranging from 0 to 2
    :param v0: nx1 Matrix
    :param v1: nx1 Matrix
    """
    return 1 - ((dot(v0.T, v1))[0] / (norm(v0) * norm(v1)))


def euclidean_distance(v1, v2):
    """
    :param v1: nx1 Matrix
    :param v2: nx1 Matrix
    """
    return norm(v1 - v2)


def fmod(a, b):
    a = Expression(a).s
    b = Expression(b).s
    return Expression(ca.fmod(a, b))


def euclidean_division(nominator, denominator):
    pass


def normalize_angle_positive(angle):
    """
    Normalizes the angle to be 0 to 2*pi
    It takes and returns radians.
    """
    return fmod(fmod(angle, 2.0 * ca.pi) + 2.0 * ca.pi, 2.0 * ca.pi)


def normalize_angle(angle):
    """
    Normalizes the angle to be -pi to +pi
    It takes and returns radians.
    """
    a = normalize_angle_positive(angle)
    return if_greater(a, ca.pi, a - 2.0 * ca.pi, a)


def shortest_angular_distance(from_angle, to_angle):
    """
    Given 2 angles, this returns the shortest angular
    difference.  The inputs and outputs are of course radians.

    The result would always be -pi <= result <= pi. Adding the result
    to "from" will always get you an equivalent angle to "to".
    """
    return normalize_angle(to_angle - from_angle)


def quaternion_slerp(q1, q2, t):
    """
    spherical linear interpolation that takes into account that q == -q
    :param q1: 4x1 Matrix
    :param q2: 4x1 Matrix
    :param t: float, 0-1
    :return: 4x1 Matrix; Return spherical linear interpolation between two quaternions.
    """
    q1 = Expression(q1)
    q2 = Expression(q2)
    cos_half_theta = q1.dot(q2)

    if0 = -cos_half_theta
    q2 = if_greater_zero(if0, -q2, q2)
    cos_half_theta = if_greater_zero(if0, -cos_half_theta, cos_half_theta)

    if1 = abs(cos_half_theta) - 1.0

    # enforce acos(x) with -1 < x < 1
    cos_half_theta = min(1, cos_half_theta)
    cos_half_theta = max(-1, cos_half_theta)

    half_theta = acos(cos_half_theta)

    sin_half_theta = sqrt(1.0 - cos_half_theta * cos_half_theta)
    if2 = 0.001 - abs(sin_half_theta)

    ratio_a = save_division(sin((1.0 - t) * half_theta), sin_half_theta)
    ratio_b = save_division(sin(t * half_theta), sin_half_theta)
    return Quaternion(if_greater_eq_zero(if1,
                                         q1,
                                         if_greater_zero(if2,
                                                         0.5 * q1 + 0.5 * q2,
                                                         ratio_a * q1 + ratio_b * q2)))


def slerp(v1, v2, t):
    """
    spherical linear interpolation
    :param v1: any vector
    :param v2: vector of same length as v1
    :param t: value between 0 and 1. 0 is v1 and 1 is v2
    """
    angle = save_acos(dot(v1, v2))
    angle2 = if_eq(angle, 0, 1, angle)
    return if_eq(angle, 0,
                 v1,
                 (sin((1 - t) * angle2) / sin(angle2)) * v1 + (sin(t * angle2) / sin(angle2)) * v2)


def save_division(nominator, denominator, if_nan=None):
    if if_nan is None:
        if isinstance(nominator, Vector3):
            if_nan = Vector3()
        elif isinstance(nominator, Point3):
            if_nan = Vector3
        else:
            if_nan = 0
    save_denominator = if_eq_zero(denominator, 1, denominator)
    return nominator * if_eq_zero(denominator, if_nan, 1. / save_denominator)


def save_acos(angle):
    angle = limit(angle, -1, 1)
    return acos(angle)


def entrywise_product(matrix1, matrix2):
    assert matrix1.shape == matrix2.shape
    result = zeros(*matrix1.shape)
    for i in range(matrix1.shape[0]):
        for j in range(matrix1.shape[1]):
            result[i, j] = matrix1[i, j] * matrix2[i, j]
    return result


def floor(x):
    x = Expression(x).s
    return Expression(ca.floor(x))


def ceil(x):
    x = Expression(x).s
    return Expression(ca.ceil(x))


def round_up(x, decimal_places):
    f = 10 ** (decimal_places)
    return ceil(x * f) / f


def round_down(x, decimal_places):
    f = 10 ** (decimal_places)
    return floor(x * f) / f


def sum(matrix):
    """
    the equivalent to np.sum(matrix)
    """
    matrix = Expression(matrix).s
    return Expression(ca.sum1(ca.sum2(matrix)))


def sum_row(matrix: Expression) -> Expression:
    """
    the equivalent to np.sum(matrix, axis=0)
    """
    matrix = Expression(matrix).s
    return Expression(ca.sum1(matrix))


def sum_column(matrix):
    """
    the equivalent to np.sum(matrix, axis=1)
    """
    matrix = Expression(matrix).s
    return Expression(ca.sum2(matrix))


def distance_point_to_line_segment(frame_P_current, frame_P_line_start, frame_P_line_end):
    """
    :param frame_P_current: current position of an object (i. e.) gripper tip
    :param frame_P_line_start: start of the approached line
    :param frame_P_line_end: end of the approached line
    :return: distance to line, the nearest point on the line
    """
    frame_P_current = Point3(frame_P_current)
    frame_P_line_start = Point3(frame_P_line_start)
    frame_P_line_end = Point3(frame_P_line_end)
    line_vec = frame_P_line_end - frame_P_line_start
    pnt_vec = frame_P_current - frame_P_line_start
    line_len = norm(line_vec)
    line_unitvec = line_vec / line_len
    pnt_vec_scaled = pnt_vec / line_len
    t = line_unitvec.dot(pnt_vec_scaled)
    t = limit(t, lower_limit=0.0, upper_limit=1.0)
    nearest = line_vec * t
    dist = norm(nearest - pnt_vec)
    nearest = nearest + frame_P_line_start
    return dist, Point3(nearest)


def distance_point_to_line(frame_P_point, frame_P_line_point, frame_V_line_direction):
    frame_P_current = Point3(frame_P_point)
    frame_P_line_point = Point3(frame_P_line_point)
    frame_V_line_direction = Vector3(frame_V_line_direction)

    lp_vector = frame_P_current - frame_P_line_point
    cross_product = cross(lp_vector, frame_V_line_direction)
    distance = norm(cross_product) / norm(frame_V_line_direction)
    return distance


def distance_point_to_plane(frame_P_current, frame_V_v1, frame_V_v2):
    normal = cross(frame_V_v1, frame_V_v2)
    d = normal.dot(frame_P_current)
    normal.scale(d)
    nearest = frame_P_current - normal
    return norm(nearest - frame_P_current), nearest


def distance_point_to_plane_signed(frame_P_current, frame_V_v1, frame_V_v2):
    normal = cross(frame_V_v1, frame_V_v2)
    normal = normal / norm(normal)  # Normalize the normal vector
    d = normal.dot(frame_P_current)  # Signed distance to the plane
    nearest = frame_P_current - normal * d  # Nearest point on the plane
    return d, nearest


def project_to_cone(frame_V_current, frame_V_cone_axis, cone_theta):
    frame_V_cone_axis_norm = frame_V_cone_axis / norm(frame_V_cone_axis)
    beta = dot(frame_V_current, frame_V_cone_axis_norm)
    norm_v = norm(frame_V_current)

    # Compute the perpendicular component.
    v_perp = frame_V_current - beta * frame_V_cone_axis_norm
    norm_v_perp = norm(v_perp)

    s = beta * cos(cone_theta) + norm_v_perp * sin(cone_theta)

    # Handle the case when v is collinear with a.
    project_on_cone_boundary = if_less(a=norm_v_perp, b=1e-8,
                                       if_result=norm_v * cos(cone_theta) * frame_V_cone_axis_norm,
                                       else_result=s * (cos(cone_theta) * frame_V_cone_axis_norm + sin(cone_theta) * (
                                               v_perp / norm_v_perp)))

    return if_greater_eq(a=beta, b=norm_v * np.cos(cone_theta),
                         if_result=frame_V_current,
                         else_result=project_on_cone_boundary)


def project_to_plane(frame_V_plane_vector1, frame_V_plane_vector2, frame_P_point):
    """
    Projects a point onto a plane defined by two vectors.
    This function assumes that all parameters are defined with respect to the same reference frame.

    :param frame_V_plane_vector1: First vector defining the plane
    :param frame_V_plane_vector2: Second vector defining the plane
    :param frame_P_point: Point to project onto the plane
    :return: The projected point on the plane
    """
    normal = cross(frame_V_plane_vector1, frame_V_plane_vector2)
    normal.scale(1)
    d = normal.dot(frame_P_point)
    projection = frame_P_point - normal * d
    return Point3(projection, reference_frame=frame_P_point.reference_frame)


def angle_between_vector(v1, v2):
    v1 = v1[:3]
    v2 = v2[:3]
    return acos(limit(dot(v1.T, v2) / (norm(v1) * norm(v2)),
                      lower_limit=-1,
                      upper_limit=1))


def rotational_error(r1, r2):
    r_distance = r1.dot(r2.inverse())
    return r_distance.to_angle()


def velocity_limit_from_position_limit(acceleration_limit,
                                       position_limit,
                                       current_position,
                                       step_size,
                                       eps=1e-5):
    """
    Computes the velocity limit given a distance to the position limits, an acceleration limit and a step size
    :param acceleration_limit:
    :param step_size:
    :param eps:
    :return:
    """
    distance_to_position_limit = position_limit - current_position
    acceleration_limit *= step_size
    distance_to_position_limit /= step_size
    m = 1 / acceleration_limit
    acceleration_limit *= m
    distance_to_position_limit *= m
    sign_ = sign(distance_to_position_limit)
    error = abs(distance_to_position_limit)
    # reverse gausssche summenformel to compute n from sum
    n = sqrt(2 * error + (1 / 4)) - 1 / 2
    # round up if very close to the ceiling to avoid precision errors
    n = if_less(1 - (n - floor(n)), eps, ceil(n), floor(n))
    error_rounded = (n ** 2 + n) / 2
    rest = error - error_rounded
    rest = rest / (n + 1)
    velocity_limit = n + rest
    velocity_limit *= sign_
    velocity_limit /= m
    return Expression(velocity_limit)


def to_str(expression):
    """
    Turns expression into a more or less readable string.
    """
    result_list = np.zeros(expression.shape).tolist()
    for x_index in range(expression.shape[0]):
        for y_index in range(expression.shape[1]):
            s = str(expression[x_index, y_index])
            parts = s.split(', ')
            result = parts[-1]
            for x in reversed(parts[:-1]):
                equal_position = len(x.split('=')[0])
                index = x[:equal_position]
                sub = x[equal_position + 1:]
                if index not in result:
                    raise Exception('fuck')
                result = result.replace(index, sub)
            result_list[x_index][y_index] = result
    return result_list


def total_derivative(expr,
                     symbols,
                     symbols_dot):
    symbols = Expression(symbols)
    symbols_dot = Expression(symbols_dot)
    return Expression(ca.jtimes(expr.s, symbols.s, symbols_dot.s))


def total_derivative2(expr, symbols, symbols_dot, symbols_ddot):
    symbols = Expression(symbols)
    symbols_dot = Expression(symbols_dot)
    symbols_ddot = Expression(symbols_ddot)
    v = []
    for i in range(len(symbols)):
        for j in range(len(symbols)):
            if i == j:
                v.append(symbols_ddot[i].s)
            else:
                v.append(symbols_dot[i].s * symbols_dot[j].s)
    v = Expression(v)
    H = Expression(ca.hessian(expr.s, symbols.s)[0])
    H = H.reshape((1, len(H) ** 2))
    return H.dot(v)


def quaternion_multiply(q1, q2):
    q1 = Quaternion(q1)
    q2 = Quaternion(q2)
    return q1.multiply(q2)


def quaternion_conjugate(q):
    q1 = Quaternion(q)
    return q1.conjugate()


def quaternion_diff(q1, q2):
    q1 = Quaternion(q1)
    q2 = Quaternion(q2)
    return q1.diff(q2)


def sign(x):
    x = Expression(x).s
    return Expression(ca.sign(x))


def cos(x):
    x = Expression(x).s
    return Expression(ca.cos(x))


def sin(x):
    x = Expression(x).s
    return Expression(ca.sin(x))


def exp(x):
    x = Expression(x).s
    return Expression(ca.exp(x))


def log(x):
    x = Expression(x).s
    return Expression(ca.log(x))


def tan(x):
    x = Expression(x).s
    return Expression(ca.tan(x))


def cosh(x):
    x = Expression(x).s
    return Expression(ca.cosh(x))


def sinh(x):
    x = Expression(x).s
    return Expression(ca.sinh(x))


def sqrt(x):
    x = Expression(x).s
    return Expression(ca.sqrt(x))


def acos(x):
    x = Expression(x).s
    return Expression(ca.acos(x))


def atan2(x, y):
    x = Expression(x).s
    y = Expression(y).s
    return Expression(ca.atan2(x, y))


def solve_for(expression, target_value, start_value=0.0001, max_tries=10000, eps=1e-10, max_step=50):
    f_dx = jacobian(expression, expression.free_symbols()).compile()
    f = expression.compile()
    x = start_value
    for tries in range(max_tries):
        err = f.fast_call(np.array([x]))[0] - target_value
        if builtin_abs(err) < eps:
            return x
        slope = f_dx.fast_call(np.array([x]))[0]
        if slope == 0:
            if start_value > 0:
                slope = -0.001
            else:
                slope = 0.001
        x -= builtin_max(builtin_min(err / slope, max_step), -max_step)
    raise ValueError('no solution found')


def gauss(n):
    return (n ** 2 + n) / 2


def r_gauss(integral):
    return sqrt(2 * integral + (1 / 4)) - 1 / 2


def one_step_change(current_acceleration, jerk_limit, dt):
    return current_acceleration * dt + jerk_limit * dt ** 2


def desired_velocity(current_position, goal_position, dt, ph):
    e = goal_position - current_position
    a = e / (gauss(ph) * dt)
    # a = e / ((gauss(ph-1) + ph - 1)*dt)
    return a * ph
    # return a * (ph-2)


def vel_integral(vel_limit, jerk_limit, dt, ph):
    def f(vc, ac, jl, t, dt, ph):
        return vc + (t) * ac * dt + gauss(t) * jl * dt ** 2

    half1 = math.floor(ph / 2)
    x = f(0, 0, jerk_limit, half1, dt, ph)
    return x


def substitute(expression, old_symbols, new_symbols):
    sx = expression.s
    old_symbols = Expression([_to_sx(s) for s in old_symbols]).s
    new_symbols = Expression([_to_sx(s) for s in new_symbols]).s
    sx = ca.substitute(sx, old_symbols, new_symbols)
    result = copy(expression)
    result.s = sx
    return result


def matrix_inverse(a):
    if isinstance(a, TransformationMatrix):
        return a.inverse()
    return Expression(ca.inv(a.s))


def gradient(ex, arg):
    return Expression(ca.gradient(ex.s, arg.s))


def is_true_symbol(expr):
    try:
        return (expr == BinaryTrue).to_np()
    except Exception as e:
        return False


def is_true3(expr):
    return equal(expr, TrinaryTrue)


def is_true3_symbol(expr):
    try:
        return (expr == TrinaryTrue).to_np()
    except Exception as e:
        return False


def is_false_symbol(expr):
    try:
        return (expr == BinaryFalse).to_np()
    except Exception as e:
        return False


def is_false3(expr):
    return equal(expr, TrinaryFalse)


def is_false3_symbol(expr):
    try:
        return (expr == TrinaryFalse).to_np()
    except Exception as e:
        return False


def is_unknown3(expr):
    return equal(expr, TrinaryUnknown)


def is_unknown3_symbol(expr):
    try:
        return (expr == TrinaryUnknown).to_np()
    except Exception as e:
        return False


def is_constant(expr):
    if isinstance(expr, (float, int)):
        return True
    return len(free_symbols(_to_sx(expr))) == 0


def det(expr):
    return Expression(ca.det(expr.s))


def distance_projected_on_vector(point1, point2, vector):
    dist = point1 - point2
    projection = dot(dist, vector)
    return projection


def distance_vector_projected_on_plane(point1, point2, normal_vector):
    dist = point1 - point2
    projection = dist - dot(dist, normal_vector) * normal_vector
    return projection


def replace_with_three_logic(expr):
    cas_expr = _to_sx(expr)
    if cas_expr.n_dep() == 0:
        if is_true_symbol(cas_expr):
            return TrinaryTrue
        if is_false_symbol(cas_expr):
            return TrinaryFalse
        return expr
    op = cas_expr.op()
    if op == ca.OP_NOT:
        return logic_not3(replace_with_three_logic(cas_expr.dep(0)))
    if op == ca.OP_AND:
        return logic_and3(replace_with_three_logic(cas_expr.dep(0)),
                          replace_with_three_logic(cas_expr.dep(1)))
    if op == ca.OP_OR:
        return logic_or3(replace_with_three_logic(cas_expr.dep(0)),
                         replace_with_three_logic(cas_expr.dep(1)))
    return expr


def is_inf(expr):
    cas_expr = _to_sx(expr)
    if is_constant(expr):
        return np.isinf(ca.evalf(expr).full()[0][0])
    for arg in range(cas_expr.n_dep()):
        if is_inf(cas_expr.dep(arg)):
            return True
    return False
