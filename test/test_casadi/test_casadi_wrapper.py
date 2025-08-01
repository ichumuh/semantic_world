import math
import pytest
from datetime import timedelta
import semantic_world.spatial_types.math as giskard_math
import hypothesis.strategies as st
import numpy as np
from hypothesis import given, assume, settings
import semantic_world.spatial_types.spatial_types as cas
from .utils_for_tests import float_no_nan_no_inf, quaternion, random_angle, unit_vector, compare_axis_angle, \
    angle_positive, vector, lists_of_same_length, compare_orientations, sq_matrix, float_no_nan_no_inf_min_max


def logic_not(a):
    if a == cas.TrinaryTrue:
        return cas.TrinaryFalse
    elif a == cas.TrinaryFalse:
        return cas.TrinaryTrue
    elif a == cas.TrinaryUnknown:
        return cas.TrinaryUnknown
    else:
        raise ValueError(f'Invalid truth value: {a}')


def logic_and(a, b):
    if a == cas.TrinaryFalse or b == cas.TrinaryFalse:
        return cas.TrinaryFalse
    elif a == cas.TrinaryTrue and b == cas.TrinaryTrue:
        return cas.TrinaryTrue
    elif a == cas.TrinaryUnknown or b == cas.TrinaryUnknown:
        return cas.TrinaryUnknown
    else:
        raise ValueError(f'Invalid truth values: {a}, {b}')


def logic_or(a, b):
    if a == cas.TrinaryTrue or b == cas.TrinaryTrue:
        return cas.TrinaryTrue
    elif a == cas.TrinaryFalse and b == cas.TrinaryFalse:
        return cas.TrinaryFalse
    elif a == cas.TrinaryUnknown or b == cas.TrinaryUnknown:
        return cas.TrinaryUnknown
    else:
        raise ValueError(f'Invalid truth values: {a}, {b}')


class TestUndefinedLogic:
    values = [cas.TrinaryTrue, cas.TrinaryFalse, cas.TrinaryUnknown]

    def test_and3(self):
        s = cas.Symbol('a')
        s2 = cas.Symbol('b')
        expr = cas.logic_and3(s, s2)
        f = expr.compile()
        for i in self.values:
            for j in self.values:
                expected = logic_and(i, j)
                actual = f(a=i, b=j)
                assert expected == actual, f'a={i}, b={j}, expected {expected}, actual {actual}'

    def test_or3(self):
        s = cas.Symbol('a')
        s2 = cas.Symbol('b')
        expr = cas.logic_or3(s, s2)
        f = expr.compile()
        for i in self.values:
            for j in self.values:
                expected = logic_or(i, j)
                actual = f(a=i, b=j)
                assert expected == actual, f'a={i}, b={j}, expected {expected}, actual {actual}'

    def test_not3(self):
        s = cas.Symbol('muh')
        expr = cas.logic_not3(s)
        f = expr.compile()
        for i in self.values:
            expected = logic_not(i)
            actual = f(muh=i)
            assert expected == actual, f'a={i}, expected {expected}, actual {actual}'

    def test_sub_logic_operators(self):
        def reference_function(a, b, c):
            not_c = logic_not(c)
            or_result = logic_or(b, not_c)
            result = logic_and(a, or_result)
            return result

        a, b, c = cas.create_symbols(['a', 'b', 'c'])
        expr = cas.logic_and(a, cas.logic_or(b, cas.logic_not(c)))
        new_expr = cas.replace_with_three_logic(expr)
        f = new_expr.compile()
        for i in self.values:
            for j in self.values:
                for k in self.values:
                    computed_result = f(a=i, b=j, c=k)
                    expected_result = reference_function(i, j, k)
                    assert computed_result == expected_result, f"Mismatch for inputs i={i}, j={j}, k={k}. Expected {expected_result}, got {computed_result}"


class TestSymbol:
    def test_from_name(self):
        s = cas.Symbol('muh')
        assert isinstance(s, cas.Symbol)
        assert str(s) == 'muh'

    def test_simple_math(self):
        s = cas.Symbol('muh')
        e = s + s
        assert isinstance(e, cas.Expression)
        e = s - s
        assert isinstance(e, cas.Expression)
        e = s * s
        assert isinstance(e, cas.Expression)
        e = s / s
        assert isinstance(e, cas.Expression)
        e = s ** s
        assert isinstance(e, cas.Expression)

    def test_comparisons(self):
        s = cas.Symbol('muh')
        e = s > s
        assert isinstance(e, cas.Expression)
        e = s >= s
        assert isinstance(e, cas.Expression)
        e = s < s
        assert isinstance(e, cas.Expression)
        e = s <= s
        assert isinstance(e, cas.Expression)
        e = cas.equal(s, s)
        assert isinstance(e, cas.Expression)

    def test_logic(self):
        s1 = cas.Symbol('s1')
        s2 = cas.Symbol('s2')
        s3 = cas.Symbol('s3')
        e = s1 | s2
        assert isinstance(e, cas.Expression)
        e = s1 & s2
        assert isinstance(e, cas.Expression)
        e = ~s1
        assert isinstance(e, cas.Expression)
        e = s1 & (s2 | ~s3)
        assert isinstance(e, cas.Expression)

    def test_hash(self):
        s = cas.Symbol('muh')
        d = {s: 1}
        assert d[s] == 1


class TestExpression:
    def test_pretty_str(self):
        e = cas.eye(4)
        e.pretty_str()

    def test_create(self):
        cas.Expression(cas.Symbol('muh'))
        cas.Expression([cas.ca.SX(1), cas.ca.SX.sym('muh')])
        m = cas.Expression(np.eye(4))
        m = cas.Expression(m)
        assert np.allclose(m.to_np(), np.eye(4))
        m = cas.Expression(cas.ca.SX(np.eye(4)))
        assert np.allclose(m.to_np(), np.eye(4))
        m = cas.Expression([1, 1])
        assert np.allclose(m.to_np(), np.array([1, 1]))
        m = cas.Expression([np.array([1, 1])])
        assert np.allclose(m.to_np(), np.array([1, 1]))
        m = cas.Expression(1)
        assert m.to_np() == 1
        m = cas.Expression([[1, 1], [2, 2]])
        assert np.allclose(m.to_np(), np.array([[1, 1], [2, 2]]))
        m = cas.Expression([])
        assert m.shape[0] == m.shape[1] == 0
        m = cas.Expression()
        assert m.shape[0] == m.shape[1] == 0

    def test_filter1(self):
        e_np = np.arange(16) * 2
        e = cas.Expression(e_np)
        filter_ = np.zeros(16, dtype=bool)
        filter_[3] = True
        filter_[5] = True
        actual = e[filter_].to_np()
        expected = e_np[filter_]
        assert np.all(actual == expected)

    def test_filter2(self):
        e_np = np.arange(16) * 2
        e_np = e_np.reshape((4, 4))
        e = cas.Expression(e_np)
        filter_ = np.zeros(4, dtype=bool)
        filter_[1] = True
        filter_[2] = True
        actual = e[filter_].to_np()
        expected = e_np[filter_]
        assert np.allclose(actual, expected)

    @given(float_no_nan_no_inf(), float_no_nan_no_inf())
    def test_add(self, f1, f2):
        expected = f1 + f2
        r1 = cas.compile_and_execute(lambda a: cas.Expression(a) + f1, [f2])
        assert np.isclose(r1, expected)
        r1 = cas.compile_and_execute(lambda a: f1 + cas.Expression(a), [f2])
        assert np.isclose(r1, expected)
        r1 = cas.compile_and_execute(lambda a, b: cas.Expression(a) + cas.Expression(b), [f1, f2])
        assert np.isclose(r1, expected)

    @given(float_no_nan_no_inf(), float_no_nan_no_inf())
    def test_sub(self, f1, f2):
        expected = f1 - f2
        r1 = cas.compile_and_execute(lambda a: cas.Expression(a) - f2, [f1])
        np.isclose(r1, expected)
        r1 = cas.compile_and_execute(lambda a: f1 - cas.Expression(a), [f2])
        np.isclose(r1, expected)
        r1 = cas.compile_and_execute(lambda a, b: cas.Expression(a) - cas.Expression(b), [f1, f2])
        np.isclose(r1, expected)

    def test_len(self):
        m = cas.Expression(np.eye(4))
        assert (len(m) == len(np.eye(4)))

    def test_simple_math(self):
        m = cas.Expression([1, 1])
        s = cas.Symbol('muh')
        e = m + s
        e = m + 1
        e = 1 + m
        assert isinstance(e, cas.Expression)
        e = m - s
        e = m - 1
        e = 1 - m
        assert isinstance(e, cas.Expression)
        e = m * s
        e = m * 1
        e = 1 * m
        assert isinstance(e, cas.Expression)
        e = m / s
        e = m / 1
        e = 1 / m
        assert isinstance(e, cas.Expression)
        e = m ** s
        e = m ** 1
        e = 1 ** m
        assert isinstance(e, cas.Expression)

    def test_get_attr(self):
        m = cas.Expression(np.eye(4))
        assert m[0, 0] == cas.Expression(1)
        assert m[1, 1] == cas.Expression(1)
        assert m[1, 0] == cas.Expression(0)
        assert isinstance(m[0, 0], cas.Expression)
        print(m.shape)

    def test_comparisons(self):
        logic_functions = [
            lambda a, b: a > b,
            lambda a, b: a >= b,
            lambda a, b: a < b,
            lambda a, b: a <= b,
            lambda a, b: a == b,
        ]
        e1_np = np.array([1, 2, 3, -1])
        e2_np = np.array([1, 1, -1, 3])
        e1_cas = cas.Expression(e1_np)
        e2_cas = cas.Expression(e2_np)
        for f in logic_functions:
            r_np = f(e1_np, e2_np)
            r_cas = f(e1_cas, e2_cas)
            assert isinstance(r_cas, cas.Expression)
            r_cas = r_cas.to_np()
            np.all(r_np == r_cas)

    def test_logic_and(self):
        s1 = cas.Symbol('s1')
        s2 = cas.Symbol('s2')
        expr = cas.logic_and(cas.BinaryTrue, s1)
        assert not cas.is_true_symbol(expr) and not cas.is_false_symbol(expr)
        expr = cas.logic_and(cas.BinaryFalse, s1)
        assert cas.is_false_symbol(expr)
        expr = cas.logic_and(cas.BinaryTrue, cas.BinaryTrue)
        assert cas.is_true_symbol(expr)
        expr = cas.logic_and(cas.BinaryFalse, cas.BinaryTrue)
        assert cas.is_false_symbol(expr)
        expr = cas.logic_and(cas.BinaryFalse, cas.BinaryFalse)
        assert cas.is_false_symbol(expr)
        expr = cas.logic_and(s1, s2)
        assert not cas.is_true_symbol(expr) and not cas.is_false_symbol(expr)

    def test_logic_or(self):
        s1 = cas.Symbol('s1')
        s2 = cas.Symbol('s2')
        s3 = cas.Symbol('s3')
        expr = cas.logic_or(cas.BinaryFalse, s1)
        assert not cas.is_true_symbol(expr) and not cas.is_false_symbol(expr)
        expr = cas.logic_or(cas.BinaryTrue, s1)
        assert cas.is_true_symbol(expr)
        expr = cas.logic_or(cas.BinaryTrue, cas.BinaryTrue)
        assert cas.is_true_symbol(expr)
        expr = cas.logic_or(cas.BinaryFalse, cas.BinaryTrue)
        assert cas.is_true_symbol(expr)
        expr = cas.logic_or(cas.BinaryFalse, cas.BinaryFalse)
        assert cas.is_false_symbol(expr)
        expr = cas.logic_or(s1, s2)
        assert not cas.is_true_symbol(expr) and not cas.is_false_symbol(expr)

        expr = cas.logic_or(s1, s2, s3)
        assert not cas.is_true_symbol(expr) and not cas.is_false_symbol(expr)

    def test_lt(self):
        e1 = cas.Expression([1, 2, 3, -1])
        e2 = cas.Expression([1, 1, -1, 3])
        gt_result = e1 < e2
        assert isinstance(gt_result, cas.Expression)
        assert cas.logic_all(gt_result == cas.Expression([0, 0, 0, 1])).to_np()


class TestRotationMatrix:
    def test_transpose(self):
        # todo
        pass

    def test_create_RotationMatrix(self):
        s = cas.Symbol('s')
        r = cas.RotationMatrix.from_rpy(1, 2, s)
        r = cas.RotationMatrix.from_rpy(1, 2, 3)
        assert isinstance(r, cas.RotationMatrix)
        t = cas.TransformationMatrix.from_xyz_rpy(1, 2, 3)
        r = cas.RotationMatrix(t)
        assert t[0, 3].to_np() == 1

    @given(quaternion())
    def test_from_quaternion(self, q):
        actual = cas.RotationMatrix.from_quaternion(cas.Quaternion(q)).to_np()
        expected = giskard_math.rotation_matrix_from_quaternion(*q)
        assert np.allclose(actual, expected)

    @given(random_angle(),
           random_angle(),
           random_angle())
    def test_rotation_matrix_from_rpy(self, roll, pitch, yaw):
        m1 = cas.compile_and_execute(cas.RotationMatrix.from_rpy, [roll, pitch, yaw])
        m2 = giskard_math.rotation_matrix_from_rpy(roll, pitch, yaw)
        assert np.allclose(m1, m2)

    @given(unit_vector(length=3),
           random_angle())
    def test_rotation3_axis_angle(self, axis, angle):
        assert np.allclose(cas.compile_and_execute(cas.RotationMatrix.from_axis_angle,
                                                                     [axis, angle]),
                                             giskard_math.rotation_matrix_from_axis_angle(np.array(axis), angle))

    @given(quaternion())
    def test_axis_angle_from_matrix(self, q):
        m = giskard_math.rotation_matrix_from_quaternion(*q)
        actual_axis = cas.compile_and_execute(lambda x: cas.RotationMatrix(x).to_axis_angle()[0], [m])
        actual_angle = cas.compile_and_execute(lambda x: cas.RotationMatrix(x).to_axis_angle()[1], [m])
        expected_axis, expected_angle = giskard_math.axis_angle_from_rotation_matrix(m)
        compare_axis_angle(actual_angle, actual_axis[:3], expected_angle, expected_axis)
        assert actual_axis[-1] == 0

    @given(unit_vector(length=3),
           angle_positive())
    def test_axis_angle_from_matrix2(self, expected_axis, expected_angle):
        m = giskard_math.rotation_matrix_from_axis_angle(expected_axis, expected_angle)
        actual_axis = cas.compile_and_execute(lambda x: cas.RotationMatrix(x).to_axis_angle()[0], [m])
        actual_angle = cas.compile_and_execute(lambda x: cas.RotationMatrix(x).to_axis_angle()[1], [m])
        compare_axis_angle(actual_angle, actual_axis[:3], expected_angle, expected_axis)
        assert actual_axis[-1] == 0

    @given(unit_vector(4))
    def test_rpy_from_matrix(self, q):
        matrix = giskard_math.rotation_matrix_from_quaternion(*q)
        roll = cas.compile_and_execute(lambda m: cas.RotationMatrix(m).to_rpy()[0], [matrix])
        pitch = cas.compile_and_execute(lambda m: cas.RotationMatrix(m).to_rpy()[1], [matrix])
        yaw = cas.compile_and_execute(lambda m: cas.RotationMatrix(m).to_rpy()[2], [matrix])
        roll2, pitch2, yaw2 = giskard_math.rpy_from_matrix(matrix)
        assert np.isclose(roll, roll2)
        assert np.isclose(pitch, pitch2)
        assert np.isclose(yaw, yaw2)

    @given(unit_vector(4))
    def test_rpy_from_matrix2(self, q):
        matrix = giskard_math.rotation_matrix_from_quaternion(*q)
        roll = cas.compile_and_execute(lambda m: cas.RotationMatrix(m).to_rpy()[0], [matrix])
        pitch = cas.compile_and_execute(lambda m: cas.RotationMatrix(m).to_rpy()[1], [matrix])
        yaw = cas.compile_and_execute(lambda m: cas.RotationMatrix(m).to_rpy()[2], [matrix])
        r1 = cas.compile_and_execute(cas.RotationMatrix.from_rpy, [roll, pitch, yaw])
        assert np.allclose(r1, matrix, atol=1.e-4)


class TestPoint3:

    @given(vector(3))
    def test_norm(self, v):
        p = cas.Point3(v)
        actual = p.norm().to_np()
        expected = np.linalg.norm(v)
        np.isclose(actual, expected)

    @given(vector(3))
    def test_point3(self, v):
        cas.Point3()
        r1 = cas.Point3(v)
        assert r1[0] == v[0]
        assert r1[1] == v[1]
        assert r1[2] == v[2]
        assert r1[3] == 1
        cas.Point3(cas.Expression(v))
        cas.Point3(cas.Point3(v))
        cas.Point3(cas.Vector3(v))
        cas.Point3(cas.Expression(v).s)
        cas.Point3(np.array(v))

    def test_point3_sub(self):
        p1 = cas.Point3((1, 1, 1))
        p2 = cas.Point3((1, 1, 1))
        p3 = p1 - p2
        assert isinstance(p3, cas.Vector3)
        assert p3[0] == 0
        assert p3[1] == 0
        assert p3[2] == 0
        assert p3[3] == 0

    def test_point3_add_vector3(self):
        p1 = cas.Point3((1, 1, 1))
        v1 = cas.Vector3((1, 1, 1))
        p3 = p1 + v1
        assert isinstance(p3, cas.Point3)
        assert p3[0] == 2
        assert p3[1] == 2
        assert p3[2] == 2
        assert p3[3] == 1

    def test_point3_mul(self):
        p1 = cas.Point3((1, 1, 1))
        s = cas.Symbol('s')
        p3 = p1 * s
        assert isinstance(p3, cas.Point3)
        f = 2
        p3 = p1 / f
        assert isinstance(p3, cas.Point3)
        assert p3[0] == 0.5
        assert p3[1] == 0.5
        assert p3[2] == 0.5
        assert p3[3] == 1

    @given(lists_of_same_length([float_no_nan_no_inf(), float_no_nan_no_inf()], min_length=3, max_length=3))
    def test_dot(self, vectors):
        u, v = vectors
        u = np.array(u)
        v = np.array(v)
        result = cas.compile_and_execute(lambda p1, p2: cas.Point3(p1).dot(cas.Point3(p2)), [u, v])
        expected = np.dot(u, v.T)
        if not np.isnan(result) and not np.isinf(result):
            assert np.isclose(result, expected)

    @given(float_no_nan_no_inf(), vector(3), vector(3))
    def test_if_greater_zero(self, condition, if_result, else_result):
        actual = cas.compile_and_execute(cas.if_greater_zero, [condition, if_result, else_result])
        expected = if_result if condition > 0 else else_result
        assert np.allclose(actual, expected)


class TestVector3:
    @given(vector(3))
    def test_norm(self, v):
        expected = np.linalg.norm(v)
        v = cas.Vector3(v)
        actual = v.norm().to_np()
        np.isclose(actual, expected)

    @given(vector(3), float_no_nan_no_inf(), vector(3))
    def test_save_division(self, nominator, denominator, if_nan):
        nominator = cas.Vector3(nominator)
        denominator = cas.Expression(denominator)
        if_nan = cas.Vector3(if_nan)
        result = cas.save_division(nominator, denominator, if_nan)

    @given(vector(3))
    def test_vector3(self, v):
        r1 = cas.Vector3(v)
        assert isinstance(r1, cas.Vector3)
        assert r1[0] == v[0]
        assert r1[1] == v[1]
        assert r1[2] == v[2]
        assert r1[3] == 0

    @given(lists_of_same_length([float_no_nan_no_inf(), float_no_nan_no_inf()], min_length=3, max_length=3))
    def test_dot(self, vectors):
        u, v = vectors
        u = np.array(u)
        v = np.array(v)
        result = cas.compile_and_execute(lambda p1, p2: cas.Vector3(p1).dot(cas.Vector3(p2)), [u, v])
        expected = np.dot(u, v.T)
        if not np.isnan(result) and not np.isinf(result):
            assert np.isclose(result, expected)


class TestTransformationMatrix:
    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_translation3(self, x, y, z):
        r1 = cas.compile_and_execute(cas.TransformationMatrix.from_xyz_rpy, [x, y, z])
        r2 = np.identity(4)
        r2[0, 3] = x
        r2[1, 3] = y
        r2[2, 3] = z
        assert np.allclose(r1, r2)

    def test_dot(self):
        s = cas.Symbol('x')
        m1 = cas.TransformationMatrix()
        m2 = cas.TransformationMatrix.from_xyz_rpy(x=s)
        m1.dot(m2)

    def test_TransformationMatrix(self):
        f = cas.TransformationMatrix.from_xyz_rpy(1, 2, 3)
        assert isinstance(f, cas.TransformationMatrix)

    @given(st.integers(min_value=1, max_value=10))
    def test_matrix(self, x_dim):
        data = list(range(x_dim))
        with pytest.raises(ValueError):
            cas.TransformationMatrix(data)

    @given(st.integers(min_value=1, max_value=10),
           st.integers(min_value=1, max_value=10))
    def test_matrix2(self, x_dim, y_dim):
        data = [[i + (j * x_dim) for j in range(y_dim)] for i in range(x_dim)]
        if x_dim != 4 or y_dim != 4:
            with pytest.raises(ValueError):
                m = cas.TransformationMatrix(data).to_np()
        else:
            m = cas.TransformationMatrix(data).to_np()
            assert float(m[3, 0]) == 0
            assert float(m[3, 1]) == 0
            assert float(m[3, 2]) == 0
            assert float(m[x_dim - 1, y_dim - 1]) == 1

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           unit_vector(length=3),
           random_angle())
    def test_frame3_axis_angle(self, x, y, z, axis, angle):
        r2 = giskard_math.rotation_matrix_from_axis_angle(np.array(axis), angle)
        r2[0, 3] = x
        r2[1, 3] = y
        r2[2, 3] = z
        r = cas.compile_and_execute(lambda x, y, z, axis, angle: cas.TransformationMatrix.from_point_rotation_matrix(
            cas.Point3((x, y, z)),
            cas.RotationMatrix.from_axis_angle(axis, angle)),
                                    [x, y, z, axis, angle])
        assert np.allclose(r, r2)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           random_angle(),
           random_angle(),
           random_angle())
    def test_frame3_rpy(self, x, y, z, roll, pitch, yaw):
        r2 = giskard_math.rotation_matrix_from_rpy(roll, pitch, yaw)
        r2[0, 3] = x
        r2[1, 3] = y
        r2[2, 3] = z
        assert np.allclose(cas.compile_and_execute(cas.TransformationMatrix.from_xyz_rpy,
                                                                     [x, y, z, roll, pitch, yaw]),
                                             r2)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           unit_vector(4))
    def test_frame3_quaternion(self, x, y, z, q):
        r2 = giskard_math.rotation_matrix_from_quaternion(*q)
        r2[0, 3] = x
        r2[1, 3] = y
        r2[2, 3] = z
        r = cas.TransformationMatrix.from_point_rotation_matrix(point=cas.Point3((x, y, z)),
                                                                rotation_matrix=cas.RotationMatrix.from_quaternion(
                                                                    cas.Quaternion(q))).to_np()
        assert np.allclose(r, r2)

    @given(float_no_nan_no_inf(outer_limit=1000),
           float_no_nan_no_inf(outer_limit=1000),
           float_no_nan_no_inf(outer_limit=1000),
           quaternion())
    def test_inverse_frame(self, x, y, z, q):
        f = giskard_math.rotation_matrix_from_quaternion(*q)
        f[0, 3] = x
        f[1, 3] = y
        f[2, 3] = z
        r = cas.compile_and_execute(lambda x: cas.TransformationMatrix(x).inverse(), [f])

        r2 = np.linalg.inv(f)
        assert np.allclose(r, r2, atol=1.e-4, rtol=1.e-4)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           unit_vector(4))
    def test_pos_of(self, x, y, z, q):
        r1 = cas.TransformationMatrix.from_point_rotation_matrix(cas.Point3((x, y, z)),
                                                                 cas.RotationMatrix.from_quaternion(
                                                                     cas.Quaternion(q))).to_position()
        r2 = [x, y, z, 1]
        for i, e in enumerate(r2):
            np.isclose(r1[i].to_np(), e)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           unit_vector(4))
    def test_trans_of(self, x, y, z, q):
        r1 = cas.TransformationMatrix.from_point_rotation_matrix(point=cas.Point3((x, y, z)),
                                                                 rotation_matrix=cas.RotationMatrix.from_quaternion(
                                                                     cas.Quaternion(q))).to_translation().to_np()
        r2 = np.identity(4)
        r2[0, 3] = x
        r2[1, 3] = y
        r2[2, 3] = z
        for i in range(r2.shape[0]):
            for j in range(r2.shape[1]):
                np.isclose(float(r1[i, j]), r2[i, j])

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           unit_vector(4))
    def test_rot_of(self, x, y, z, q):
        r1 = cas.TransformationMatrix.from_point_rotation_matrix(point=cas.Point3((x, y, z)),
                                                                 rotation_matrix=cas.RotationMatrix.from_quaternion(
                                                                     cas.Quaternion(q))).to_rotation().to_np()
        r2 = giskard_math.rotation_matrix_from_quaternion(*q)
        assert np.allclose(r1, r2)

    def test_rot_of2(self):
        """
        Test to make sure the function doesn't alter the original
        """
        f = cas.TransformationMatrix.from_xyz_rpy(1, 2, 3)
        r = f.to_rotation()
        assert f[0, 3] == 1
        assert f[0, 3] == 2
        assert f[0, 3] == 3
        assert r[0, 0] == 1
        assert r[1, 1] == 1
        assert r[2, 2] == 1


class TestQuaternion:
    @given(unit_vector(length=3),
           random_angle())
    def test_quaternion_from_axis_angle1(self, axis, angle):
        r2 = giskard_math.quaternion_from_axis_angle(axis, angle)
        assert np.allclose(cas.compile_and_execute(cas.Quaternion.from_axis_angle, [axis, angle]), r2)

    @given(quaternion(),
           quaternion())
    def test_quaternion_multiply(self, q, p):
        r1 = cas.compile_and_execute(cas.quaternion_multiply, [q, p])
        r2 = giskard_math.quaternion_multiply(q, p)
        assert np.allclose(r1, r2) or np.isclose(r1, -r2)

    @given(quaternion())
    def test_quaternion_conjugate(self, q):
        r1 = cas.compile_and_execute(cas.quaternion_conjugate, [q])
        r2 = giskard_math.quaternion_conjugate(q)
        assert np.allclose(r1, r2) or np.isclose(r1, -r2)

    @given(quaternion(),
           quaternion())
    def test_quaternion_diff(self, q1, q2):
        q3 = giskard_math.quaternion_multiply(giskard_math.quaternion_conjugate(q1), q2)
        q4 = cas.compile_and_execute(cas.quaternion_diff, [q1, q2])
        assert np.allclose(q3, q4) or np.isclose(q3, -q4)

    @given(quaternion())
    def test_axis_angle_from_quaternion(self, q):
        axis2, angle2 = giskard_math.axis_angle_from_quaternion(*q)
        axis = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[0], q)
        angle = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[1], q)
        compare_axis_angle(angle, axis[:3], angle2, axis2, 2)
        assert axis[-1] == 0

    def test_axis_angle_from_quaternion2(self):
        q = [0, 0, 0, 1.0000001]
        axis2, angle2 = giskard_math.axis_angle_from_quaternion(*q)
        axis = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[0], q)
        angle = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[1], q)
        compare_axis_angle(angle, axis[:3], angle2, axis2, 2)
        assert axis[-1] == 0

    @given(random_angle(),
           random_angle(),
           random_angle())
    def test_quaternion_from_rpy(self, roll, pitch, yaw):
        q = cas.compile_and_execute(cas.Quaternion.from_rpy, [roll, pitch, yaw])
        q2 = giskard_math.quaternion_from_rpy(roll, pitch, yaw)
        compare_orientations(q, q2)

    @given(quaternion())
    def test_quaternion_from_matrix(self, q):
        matrix = giskard_math.rotation_matrix_from_quaternion(*q)
        q2 = giskard_math.quaternion_from_rotation_matrix(matrix)
        q1_2 = cas.Quaternion.from_rotation_matrix(cas.RotationMatrix(matrix)).to_np()
        assert np.allclose(q1_2, q2) or np.allclose(q1_2, -q2)

    @given(quaternion(), quaternion())
    def test_dot(self, q1, q2):
        q1 = np.array(q1)
        q2 = np.array(q2)
        result = cas.compile_and_execute(lambda p1, p2: cas.Quaternion(p1).dot(cas.Quaternion(p2)), [q1, q2])
        expected = np.dot(q1.T, q2)
        if not np.isnan(result) and not np.isinf(result):
            assert np.isclose(result, expected)


class TestCASWrapper:
    @given(st.booleans())
    def test_empty_compiled_function(self, sparse):
        if sparse:
            expected = np.array([1, 2, 3], ndmin=2)
        else:
            expected = np.array([1, 2, 3])
        e = cas.Expression(expected)
        f = e.compile(sparse=sparse)
        assert np.allclose(f(), expected)
        assert np.allclose(f.fast_call(np.array([])), expected)

    def test_add(self):
        s2 = 'muh'
        f = 1.0
        s = cas.Symbol('s')
        e = cas.Expression(1)
        v = cas.Vector3((1, 1, 1))
        p = cas.Point3((1, 1, 1))
        t = cas.TransformationMatrix()
        r = cas.RotationMatrix()
        q = cas.Quaternion()
        # float
        assert isinstance(s + f, cas.Expression)
        assert isinstance(f + s, cas.Expression)
        assert isinstance(e + f, cas.Expression)
        assert isinstance(f + e, cas.Expression)
        assert isinstance(v + f, cas.Vector3)
        assert isinstance(f + v, cas.Vector3)
        assert isinstance(p + f, cas.Point3)
        assert isinstance(f + p, cas.Point3)
        with pytest.raises(TypeError):
            t + f
        with pytest.raises(TypeError):
            f + t
        with pytest.raises(TypeError):
            r + f
        with pytest.raises(TypeError):
            f + r
        with pytest.raises(TypeError):
            q + f
        with pytest.raises(TypeError):
            f + q

        # Symbol
        assert isinstance(s + s, cas.Expression)
        assert isinstance(s + e, cas.Expression)
        assert isinstance(e + s, cas.Expression)
        assert isinstance(s + v, cas.Vector3)
        assert isinstance(v + s, cas.Vector3)
        assert (s + v)[3].to_np() == 0 == (v + s)[3].to_np()
        assert isinstance(s + p, cas.Point3)
        assert isinstance(p + s, cas.Point3)
        assert (s + p)[3].to_np() == 1 == (p + s)[3].to_np()
        with pytest.raises(TypeError):
            s + t
        with pytest.raises(TypeError):
            t + s
        with pytest.raises(TypeError):
            s + r
        with pytest.raises(TypeError):
            r + s
        with pytest.raises(TypeError):
            s + q
        with pytest.raises(TypeError):
            q + s
        with pytest.raises(TypeError):
            s + s2
        with pytest.raises(TypeError):
            s2 + s
        # Expression
        assert isinstance(e + e, cas.Expression)
        assert isinstance(e + v, cas.Vector3)
        assert isinstance(v + e, cas.Vector3)
        assert (e + v)[3].to_np() == 0 == (v + e)[3].to_np()
        assert isinstance(e + p, cas.Point3)
        assert isinstance(p + e, cas.Point3)
        assert (e + p)[3].to_np() == 1 == (p + e)[3].to_np()
        with pytest.raises(TypeError):
            e + t
        with pytest.raises(TypeError):
            t + e
        with pytest.raises(TypeError):
            e + r
        with pytest.raises(TypeError):
            r + e
        with pytest.raises(TypeError):
            e + q
        with pytest.raises(TypeError):
            q + e
        # Vector3
        assert isinstance(v + v, cas.Vector3)
        assert (v + v)[3].to_np() == 0
        assert isinstance(v + p, cas.Point3)
        assert isinstance(p + v, cas.Point3)
        assert (v + p)[3].to_np() == 1 == (p + v)[3].to_np()
        with pytest.raises(TypeError):
            v + t
        with pytest.raises(TypeError):
            t + v
        with pytest.raises(TypeError):
            v + r
        with pytest.raises(TypeError):
            r + v
        with pytest.raises(TypeError):
            v + q
        with pytest.raises(TypeError):
            q + v
        # Point3
        with pytest.raises(TypeError):
            p + p
        with pytest.raises(TypeError):
            p + t
        with pytest.raises(TypeError):
            t + p
        with pytest.raises(TypeError):
            p + r
        with pytest.raises(TypeError):
            r + p
        with pytest.raises(TypeError):
            p + q
        with pytest.raises(TypeError):
            q + p
        # TransMatrix
        with pytest.raises(TypeError):
            t + t
        with pytest.raises(TypeError):
            t + r
        with pytest.raises(TypeError):
            r + t
        with pytest.raises(TypeError):
            t + q
        with pytest.raises(TypeError):
            q + t
        # RotationMatrix
        with pytest.raises(TypeError):
            r + r
        with pytest.raises(TypeError):
            r + q
        with pytest.raises(TypeError):
            q + r
        # Quaternion
        with pytest.raises(TypeError):
            q + q

    def test_sub(self):
        s2 = 'muh'
        f = 1.0
        s = cas.Symbol('s')
        e = cas.Expression(1)
        v = cas.Vector3((1, 1, 1))
        p = cas.Point3((1, 1, 1))
        t = cas.TransformationMatrix()
        r = cas.RotationMatrix()
        q = cas.Quaternion()
        # float
        assert isinstance(s - f, cas.Expression)
        assert isinstance(f - s, cas.Expression)
        assert isinstance(e - f, cas.Expression)
        assert isinstance(f - e, cas.Expression)
        assert isinstance(v - f, cas.Vector3)
        assert isinstance(f - v, cas.Vector3)
        assert isinstance(p - f, cas.Point3)
        assert isinstance(f - p, cas.Point3)
        with pytest.raises(TypeError):
            t - f
        with pytest.raises(TypeError):
            f - t
        with pytest.raises(TypeError):
            r - f
        with pytest.raises(TypeError):
            f - r
        with pytest.raises(TypeError):
            q - f
        with pytest.raises(TypeError):
            f - q
        # Symbol
        assert isinstance(s - s, cas.Expression)
        assert isinstance(s - e, cas.Expression)
        assert isinstance(e - s, cas.Expression)
        assert isinstance(s - v, cas.Vector3)
        assert isinstance(v - s, cas.Vector3)
        assert (s - v)[3].to_np() == 0 == (v - s)[3].to_np()
        assert isinstance(s - p, cas.Point3)
        assert isinstance(p - s, cas.Point3)
        assert (s - p)[3].to_np() == 1 == (p - s)[3].to_np()
        with pytest.raises(TypeError):
            s - t
        with pytest.raises(TypeError):
            t - s
        with pytest.raises(TypeError):
            s - r
        with pytest.raises(TypeError):
            r - s
        with pytest.raises(TypeError):
            s - q
        with pytest.raises(TypeError):
            q - s
        # Expression
        assert isinstance(e - e, cas.Expression)
        assert isinstance(e - v, cas.Vector3)
        assert isinstance(v - e, cas.Vector3)
        assert (e - v)[3].to_np() == 0 == (v - e)[3].to_np()
        assert isinstance(e - p, cas.Point3)
        assert isinstance(p - e, cas.Point3)
        assert (e - p)[3].to_np() == 1 == (p - e)[3].to_np()
        with pytest.raises(TypeError):
            e - t
        with pytest.raises(TypeError):
            t - e
        with pytest.raises(TypeError):
            e - r
        with pytest.raises(TypeError):
            r - e
        with pytest.raises(TypeError):
            e - q
        with pytest.raises(TypeError):
            q - e
        # Vector3
        assert isinstance(v - v, cas.Vector3)
        assert (v - v)[3].to_np() == 0
        assert isinstance(v - p, cas.Point3)
        assert isinstance(p - v, cas.Point3)
        assert (v - p)[3].to_np() == 1 == (p - v)[3].to_np()
        with pytest.raises(TypeError):
            v - t
        with pytest.raises(TypeError):
            t - v
        with pytest.raises(TypeError):
            v - r
        with pytest.raises(TypeError):
            r - v
        with pytest.raises(TypeError):
            v - q
        with pytest.raises(TypeError):
            q - v
        # Point3
        assert isinstance(p - p, cas.Vector3)
        assert (p - p)[3].to_np() == 0
        with pytest.raises(TypeError):
            p - t
        with pytest.raises(TypeError):
            t - p
        with pytest.raises(TypeError):
            p - r
        with pytest.raises(TypeError):
            r - p
        with pytest.raises(TypeError):
            p - q
        with pytest.raises(TypeError):
            q - p
        # TransMatrix
        with pytest.raises(TypeError):
            t - t
        with pytest.raises(TypeError):
            t - r
        with pytest.raises(TypeError):
            r - t
        with pytest.raises(TypeError):
            t - q
        with pytest.raises(TypeError):
            q - t
        # RotationMatrix
        with pytest.raises(TypeError):
            r - r
        with pytest.raises(TypeError):
            r - q
        with pytest.raises(TypeError):
            q - r
        # Quaternion
        with pytest.raises(TypeError):
            q - q

    def test_basic_operation_with_string(self):
        str_ = 'muh23'
        things = [cas.Symbol('s'),
                  cas.Expression(1),
                  cas.Vector3((1, 1, 1)),
                  cas.Point3((1, 1, 1)),
                  cas.TransformationMatrix(),
                  cas.RotationMatrix(),
                  cas.Quaternion()]
        functions = ['__add__', '__radd_', '__sub__', '__rsub__', '__mul__', '__rmul', '__truediv__', '__rtruediv__',
                     '__pow__', '__rpow__', 'dot']
        for fn in functions:
            for thing in things:
                if hasattr(str_, fn):
                    error_msg = f'string.{fn}({thing.__class__.__name__})'
                    with pytest.raises(TypeError) as e:
                        getattr(str_, fn)(thing)
                    assert 'NotImplementedType' not in str(e), error_msg
                if hasattr(thing, fn):
                    error_msg = f'{thing.__class__.__name__}.{fn}(string)'
                    with pytest.raises(TypeError) as e:
                        getattr(thing, fn)(str_)
                    assert 'NotImplementedType' not in str(e), error_msg

    def test_mul_truediv_pow(self):
        f = 1.0
        s = cas.Symbol('s')
        e = cas.Expression(1)
        v = cas.Vector3((1, 1, 1))
        p = cas.Point3((1, 1, 1))
        t = cas.TransformationMatrix()
        r = cas.RotationMatrix()
        q = cas.Quaternion()
        functions = [lambda a, b: a * b, lambda a, b: a / b, lambda a, b: a ** b]
        for fn in functions:
            # float
            assert isinstance(fn(f, s), cas.Expression)
            assert isinstance(fn(s, f), cas.Expression)
            assert isinstance(fn(f, v), cas.Vector3)
            assert isinstance(fn(v, f), cas.Vector3)
            assert isinstance(fn(f, p), cas.Point3)
            assert isinstance(fn(p, f), cas.Point3)
            with pytest.raises(TypeError):
                fn(f, t)
            with pytest.raises(TypeError):
                fn(t, f)
            with pytest.raises(TypeError):
                fn(f, r)
            with pytest.raises(TypeError):
                fn(r, f)
            with pytest.raises(TypeError):
                fn(f, q)
            with pytest.raises(TypeError):
                fn(q, f)

            # Symbol
            assert isinstance(fn(s, s), cas.Expression)
            assert isinstance(fn(s, e), cas.Expression)
            assert isinstance(fn(e, s), cas.Expression)
            assert isinstance(fn(s, v), cas.Vector3)
            assert isinstance(fn(v, s), cas.Vector3)
            assert (fn(s, v))[3].to_np() == 0 == (fn(v, s))[3].to_np()
            assert isinstance(fn(s, p), cas.Point3)
            assert isinstance(fn(p, s), cas.Point3)
            assert (fn(s, p))[3].to_np() == 1 == (fn(p, s))[3].to_np()
            with pytest.raises(TypeError):
                fn(s, t)
            with pytest.raises(TypeError):
                fn(t, s)
            with pytest.raises(TypeError):
                fn(s, r)
            with pytest.raises(TypeError):
                fn(r, s)
            with pytest.raises(TypeError):
                fn(s, q)
            with pytest.raises(TypeError):
                fn(q, s)
            # Expression
            assert isinstance(fn(e, e), cas.Expression)
            assert isinstance(fn(e, v), cas.Vector3)
            assert isinstance(fn(v, e), cas.Vector3)
            assert (fn(e, v))[3].to_np() == 0 == (fn(v, e))[3].to_np()
            assert isinstance(fn(e, p), cas.Point3)
            assert isinstance(fn(p, e), cas.Point3)
            assert (fn(e, p))[3].to_np() == 1 == (fn(p, e))[3].to_np()
            with pytest.raises(TypeError):
                fn(e, t)
            with pytest.raises(TypeError):
                fn(t, e)
            with pytest.raises(TypeError):
                fn(e, r)
            with pytest.raises(TypeError):
                fn(r, e)
            with pytest.raises(TypeError):
                fn(e, q)
            with pytest.raises(TypeError):
                fn(q, e)
            # Vector3
            with pytest.raises(TypeError):
                fn(v, v)
            with pytest.raises(TypeError):
                fn(v, p)
            with pytest.raises(TypeError):
                fn(p, v)
            with pytest.raises(TypeError):
                fn(v, t)
            with pytest.raises(TypeError):
                fn(t, v)
            with pytest.raises(TypeError):
                fn(v, r)
            with pytest.raises(TypeError):
                fn(r, v)
            with pytest.raises(TypeError):
                fn(v, q)
            with pytest.raises(TypeError):
                fn(q, v)
            # Point3
            with pytest.raises(TypeError):
                fn(p, p)
            with pytest.raises(TypeError):
                fn(p, t)
            with pytest.raises(TypeError):
                fn(t, p)
            with pytest.raises(TypeError):
                fn(p, r)
            with pytest.raises(TypeError):
                fn(r, p)
            with pytest.raises(TypeError):
                fn(p, q)
            with pytest.raises(TypeError):
                fn(q, p)
            # TransMatrix
            with pytest.raises(TypeError):
                fn(t, t)
            with pytest.raises(TypeError):
                fn(t, r)
            with pytest.raises(TypeError):
                fn(r, t)
            with pytest.raises(TypeError):
                fn(t, q)
            with pytest.raises(TypeError):
                fn(q, t)
            # RotationMatrix
            with pytest.raises(TypeError):
                fn(r, r)
            with pytest.raises(TypeError):
                fn(r, q)
            with pytest.raises(TypeError):
                fn(q, r)
            # Quaternion
            with pytest.raises(TypeError):
                fn(q, q)

    def test_dot_types(self):
        s = cas.Symbol('s')
        e = cas.Expression(1)
        v = cas.Vector3((1, 1, 1))
        p = cas.Point3((1, 1, 1))
        t = cas.TransformationMatrix()
        r = cas.RotationMatrix()
        q = cas.Quaternion()
        # Symbol
        for muh in [s, e, v, p, t, r, q]:
            with pytest.raises(TypeError):
                cas.dot(s, muh)
            with pytest.raises(TypeError):
                cas.dot(muh, s)
        # Expression
        assert isinstance(cas.dot(e, e), cas.Expression)
        assert isinstance(e.dot(e), cas.Expression)
        for muh in [v, p, t, r, q]:
            with pytest.raises(TypeError):
                cas.dot(e, muh)
            with pytest.raises(TypeError):
                cas.dot(muh, e)
            with pytest.raises(TypeError):
                e.dot(muh)
        # Vector3
        assert isinstance(v.dot(v), cas.Expression)
        assert isinstance(cas.dot(v, v), cas.Expression)
        assert isinstance(v.dot(p), cas.Expression)
        assert isinstance(cas.dot(v, p), cas.Expression)
        assert isinstance(p.dot(v), cas.Expression)
        assert isinstance(cas.dot(p, v), cas.Expression)
        assert isinstance(t.dot(v), cas.Vector3)
        assert isinstance(cas.dot(t, v), cas.Vector3)
        with pytest.raises(TypeError):
            v.dot(t)
        with pytest.raises(TypeError):
            cas.dot(v, t)
        assert isinstance(r.dot(v), cas.Vector3)
        assert isinstance(cas.dot(r, v), cas.Vector3)
        with pytest.raises(TypeError):
            v.dot(q)
        with pytest.raises(TypeError):
            cas.dot(v, q)
        with pytest.raises(TypeError):
            q.dot(v)
        with pytest.raises(TypeError):
            cas.dot(q, v)
        # Point3
        assert isinstance(p.dot(p), cas.Expression)
        assert isinstance(cas.dot(p, p), cas.Expression)
        assert isinstance(t.dot(p), cas.Point3)
        assert isinstance(cas.dot(t, p), cas.Point3)
        with pytest.raises(TypeError):
            p.dot(t)
        with pytest.raises(TypeError):
            cas.dot(p, t)
        assert isinstance(r.dot(p), cas.Point3)
        assert isinstance(cas.dot(r, p), cas.Point3)
        with pytest.raises(TypeError):
            p.dot(q)
        with pytest.raises(TypeError):
            cas.dot(p, q)
        with pytest.raises(TypeError):
            q.dot(p)
        with pytest.raises(TypeError):
            cas.dot(q, p)
        # TransMatrix
        assert isinstance(t.dot(t), cas.TransformationMatrix)
        assert isinstance(cas.dot(t, t), cas.TransformationMatrix)
        assert isinstance(t.dot(r), cas.RotationMatrix)
        assert isinstance(cas.dot(t, r), cas.RotationMatrix)
        assert isinstance(r.dot(t), cas.TransformationMatrix)
        assert isinstance(cas.dot(r, t), cas.TransformationMatrix)
        with pytest.raises(TypeError):
            t.dot(q)
        with pytest.raises(TypeError):
            cas.dot(t, q)
        with pytest.raises(TypeError):
            q.dot(t)
        with pytest.raises(TypeError):
            cas.dot(q, t)
        # RotationMatrix
        assert isinstance(r.dot(r), cas.RotationMatrix)
        assert isinstance(cas.dot(r, r), cas.RotationMatrix)
        with pytest.raises(TypeError):
            r.dot(q)
        with pytest.raises(TypeError):
            cas.dot(r, q)
        with pytest.raises(TypeError):
            q.dot(r)
        with pytest.raises(TypeError):
            cas.dot(q, r)
        assert isinstance(q.dot(q), cas.Expression)
        assert isinstance(cas.dot(q, q), cas.Expression)

    def test_free_symbols(self):
        m = cas.Expression(cas.var('a b c d'))
        assert len(cas.free_symbols(m)) == 4
        a = cas.Symbol('a')
        assert cas.equivalent(a, cas.free_symbols(a)[0])

    def test_jacobian(self):
        a = cas.Symbol('a')
        b = cas.Symbol('b')
        m = cas.Expression([a + b, a ** 2, b ** 2])
        jac = cas.jacobian(m, [a, b])
        expected = cas.Expression([[1, 1], [2 * a, 0], [0, 2 * b]])
        for i in range(expected.shape[0]):
            for j in range(expected.shape[1]):
                assert cas.equivalent(jac[i, j], expected[i, j])

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_jacobian_dot(self, a, ad, b, bd):
        kwargs = {
            'a': a,
            'ad': ad,
            'b': b,
            'bd': bd,
        }
        a_s = cas.Symbol('a')
        ad_s = cas.Symbol('ad')
        b_s = cas.Symbol('b')
        bd_s = cas.Symbol('bd')
        m = cas.Expression([
            a_s ** 3 * b_s ** 3,
            # b_s ** 2,
            -a_s * cas.cos(b_s),
            # a_s * b_s ** 4
        ])
        jac = cas.jacobian_dot(m, [a_s, b_s], [ad_s, bd_s])
        expected_expr = cas.Expression([
            [6 * ad_s * a_s * b_s ** 3 + 9 * a_s ** 2 * bd_s * b_s ** 2,
             9 * ad_s * a_s ** 2 * b_s ** 2 + 6 * a_s ** 3 * bd_s * b],
            # [0, 2 * bd_s],
            [bd_s * cas.sin(b_s), ad_s * cas.sin(b_s) + a_s * bd_s * cas.cos(b_s)],
            # [4 * bd * b ** 3, 4 * ad * b ** 3 + 12 * a * bd * b ** 2]
        ])
        actual = jac.compile()(**kwargs)
        expected = expected_expr.compile()(**kwargs)
        assert np.allclose(actual, expected)

    @given(float_no_nan_no_inf(outer_limit=1e2),
           float_no_nan_no_inf(outer_limit=1e2),
           float_no_nan_no_inf(outer_limit=1e2),
           float_no_nan_no_inf(outer_limit=1e2),
           float_no_nan_no_inf(outer_limit=1e2),
           float_no_nan_no_inf(outer_limit=1e2))
    def test_jacobian_ddot(self, a, ad, add, b, bd, bdd):
        kwargs = {
            'a': a,
            'ad': ad,
            'add': add,
            'b': b,
            'bd': bd,
            'bdd': bdd,
        }
        a_s = cas.Symbol('a')
        ad_s = cas.Symbol('ad')
        add_s = cas.Symbol('add')
        b_s = cas.Symbol('b')
        bd_s = cas.Symbol('bd')
        bdd_s = cas.Symbol('bdd')
        m = cas.Expression([
            a_s ** 3 * b_s ** 3,
            b_s ** 2,
            -a_s * cas.cos(b_s),
        ])
        jac = cas.jacobian_ddot(m, [a_s, b_s], [ad_s, bd_s], [add_s, bdd_s])
        expected = np.array([
            [add * 6 * b ** 3 + bdd * 18 * a ** 2 * b + 2 * ad * bd * 18 * a * b ** 2,
             bdd * 6 * a ** 3 + add * 18 * b ** 2 * a + 2 * ad * bd * 18 * b * a ** 2],
            [0, 0],
            [bdd * np.cos(b),
             bdd * -a * np.sin(b) + 2 * ad * bd * np.cos(b)],
        ])
        actual = jac.compile()(**kwargs)
        assert np.allclose(actual, expected)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_total_derivative2(self, a, b, ad, bd, add, bdd):
        kwargs = {
            'a': a,
            'ad': ad,
            'add': add,
            'b': b,
            'bd': bd,
            'bdd': bdd,
        }
        a_s = cas.Symbol('a')
        ad_s = cas.Symbol('ad')
        add_s = cas.Symbol('add')
        b_s = cas.Symbol('b')
        bd_s = cas.Symbol('bd')
        bdd_s = cas.Symbol('bdd')
        m = cas.Expression(a_s * b_s ** 2)
        jac = cas.total_derivative2(m, [a_s, b_s], [ad_s, bd_s], [add_s, bdd_s])
        actual = jac.compile()(**kwargs)
        expected = bdd * 2 * a + 2 * ad * bd * 2 * b
        assert np.allclose(actual, expected)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_total_derivative2_2(self, a, b, c, ad, bd, cd, add, bdd, cdd):
        kwargs = {
            'a': a,
            'ad': ad,
            'add': add,
            'b': b,
            'bd': bd,
            'bdd': bdd,
            'c': c,
            'cd': cd,
            'cdd': cdd,
        }
        a_s = cas.Symbol('a')
        ad_s = cas.Symbol('ad')
        add_s = cas.Symbol('add')
        b_s = cas.Symbol('b')
        bd_s = cas.Symbol('bd')
        bdd_s = cas.Symbol('bdd')
        c_s = cas.Symbol('c')
        cd_s = cas.Symbol('cd')
        cdd_s = cas.Symbol('cdd')
        m = cas.Expression(a_s * b_s ** 2 * c_s ** 3)
        jac = cas.total_derivative2(m, [a_s, b_s, c_s], [ad_s, bd_s, cd_s], [add_s, bdd_s, cdd_s])
        # expected_expr = cas.Expression(add_s + bdd_s*2*a*c**3 + 4*ad_s*)
        actual = jac.compile()(**kwargs)
        # expected = expected_expr.compile()(**kwargs)
        expected = bdd * 2 * a * c ** 3 \
                   + cdd * 6 * a * b ** 2 * c \
                   + 4 * ad * bd * b * c ** 3 \
                   + 6 * ad * b ** 2 * cd * c ** 2 \
                   + 12 * a * bd * b * cd * c ** 2
        assert np.allclose(actual, expected)

    def test_var(self):
        result = cas.var('a b c')
        assert str(result[0]) == 'a'
        assert str(result[1]) == 'b'
        assert str(result[2]) == 'c'

    def test_diag(self):
        result = cas.diag([1, 2, 3])
        assert result[0, 0] == 1
        assert result[0, 1] == 0
        assert result[0, 2] == 0

        assert result[1, 0] == 0
        assert result[1, 1] == 2
        assert result[1, 2] == 0

        assert result[2, 0] == 0
        assert result[2, 1] == 0
        assert result[2, 2] == 3
        assert cas.equivalent(cas.diag(cas.Expression([1, 2, 3])), cas.diag([1, 2, 3]))

    def test_vstack(self):
        m = np.eye(4)
        m1 = cas.Expression(m)
        e = cas.vstack([m1, m1])
        r1 = e.to_np()
        r2 = np.vstack([m, m])
        assert np.allclose(r1, r2)

    def test_vstack_empty(self):
        m = np.eye(0)
        m1 = cas.Expression(m)
        e = cas.vstack([m1, m1])
        r1 = e.to_np()
        r2 = np.vstack([m, m])
        assert np.allclose(r1, r2)

    def test_hstack(self):
        m = np.eye(4)
        m1 = cas.Expression(m)
        e = cas.hstack([m1, m1])
        r1 = e.to_np()
        r2 = np.hstack([m, m])
        assert np.allclose(r1, r2)

    def test_hstack_empty(self):
        m = np.eye(0)
        m1 = cas.Expression(m)
        e = cas.hstack([m1, m1])
        r1 = e.to_np()
        r2 = np.hstack([m, m])
        assert np.allclose(r1, r2)

    def test_diag_stack(self):
        m1_np = np.eye(4)
        m2_np = np.ones((2, 5))
        m3_np = np.ones((5, 3))
        m1_e = cas.Expression(m1_np)
        m2_e = cas.Expression(m2_np)
        m3_e = cas.Expression(m3_np)
        e = cas.diag_stack([m1_e, m2_e, m3_e])
        r1 = e.to_np()
        combined_matrix = np.zeros((4 + 2 + 5, 4 + 5 + 3))
        row_counter = 0
        column_counter = 0
        for matrix in [m1_np, m2_np, m3_np]:
            combined_matrix[row_counter:row_counter + matrix.shape[0],
            column_counter:column_counter + matrix.shape[1]] = matrix
            row_counter += matrix.shape[0]
            column_counter += matrix.shape[1]
        assert np.allclose(r1, combined_matrix)

    @given(float_no_nan_no_inf())
    def test_abs(self, f1):
        assert np.isclose(cas.compile_and_execute(cas.abs, [f1]), abs(f1))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_max(self, f1, f2):
        assert np.isclose(cas.compile_and_execute(cas.max, [f1, f2]), max(f1, f2))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_save_division(self, f1, f2):
        assert np.isclose(cas.compile_and_execute(cas.save_division, [f1, f2]),
                          f1 / f2 if f2 != 0 else 0)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_min(self, f1, f2):
        assert np.isclose(cas.compile_and_execute(cas.min, [f1, f2]), min(f1, f2))

    @given(float_no_nan_no_inf())
    def test_sign(self, f1):
        assert np.isclose(cas.compile_and_execute(cas.sign, [f1]), np.sign(f1))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_if_greater_zero(self, condition, if_result, else_result):
        assert np.isclose(cas.compile_and_execute(cas.if_greater_zero, [condition, if_result, else_result]),
                          float(if_result if condition > 0 else else_result))

    def test_if_one_arg(self):
        types = [cas.Point3, cas.Vector3, cas.Quaternion, cas.Expression, cas.TransformationMatrix, cas.RotationMatrix]
        if_functions = [cas.if_else, cas.if_eq_zero, cas.if_greater_eq_zero, cas.if_greater_zero]
        c = cas.Symbol('c')
        for type_ in types:
            for if_function in if_functions:
                if_result = type_()
                else_result = type_()
                result = if_function(c, if_result, else_result)
                assert isinstance(result, type_), f'{type(result)} != {type_} for {if_function}'

    def test_if_two_arg(self):
        types = [cas.Point3, cas.Vector3, cas.Quaternion, cas.Expression, cas.TransformationMatrix, cas.RotationMatrix]
        if_functions = [cas.if_eq, cas.if_greater, cas.if_greater_eq, cas.if_less, cas.if_less_eq]
        a = cas.Symbol('a')
        b = cas.Symbol('b')
        for type_ in types:
            for if_function in if_functions:
                if_result = type_()
                else_result = type_()
                assert isinstance(if_function(a, b, if_result, else_result), type_)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_if_greater_eq_zero(self, condition, if_result, else_result):
        assert np.isclose(cas.compile_and_execute(cas.if_greater_eq_zero, [condition, if_result, else_result]),
                          float(if_result if condition >= 0 else else_result))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_if_greater_eq(self, a, b, if_result, else_result):
        assert np.isclose(cas.compile_and_execute(cas.if_greater_eq, [a, b, if_result, else_result]),
                          float(if_result if a >= b else else_result))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_if_less_eq(self, a, b, if_result, else_result):
        assert np.isclose(cas.compile_and_execute(cas.if_less_eq, [a, b, if_result, else_result]),
                          float(if_result if a <= b else else_result))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_if_eq_zero(self, condition, if_result, else_result):
        assert np.isclose(cas.compile_and_execute(cas.if_eq_zero, [condition, if_result, else_result]),
                   float(if_result if condition == 0 else else_result))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_if_eq(self, a, b, if_result, else_result):
        assert np.isclose(cas.compile_and_execute(cas.if_eq, [a, b, if_result, else_result]),
                          float(if_result if a == b else else_result))

    @given(float_no_nan_no_inf())
    def test_if_eq_cases(self, a):
        b_result_cases = [(1, 1),
                          (3, 3),
                          (4, 4),
                          (-1, -1),
                          (0.5, 0.5),
                          (-0.5, -0.5)]

        def reference(a_, b_result_cases_, else_result):
            for b, if_result in b_result_cases_:
                if a_ == b:
                    return if_result
            return else_result

        actual = cas.compile_and_execute(lambda a: cas.if_eq_cases(a, b_result_cases, 0), [a])
        expected = float(reference(a, b_result_cases, 0))
        assert np.isclose(actual, expected)

    @given(float_no_nan_no_inf())
    def test_if_eq_cases_set(self, a):
        b_result_cases = {(1, 1),
                          (3, 3),
                          (4, 4),
                          (-1, -1),
                          (0.5, 0.5),
                          (-0.5, -0.5)}

        def reference(a_, b_result_cases_, else_result):
            for b, if_result in b_result_cases_:
                if a_ == b:
                    return if_result
            return else_result

        actual = cas.compile_and_execute(lambda a: cas.if_eq_cases(a, b_result_cases, 0), [a])
        expected = float(reference(a, b_result_cases, 0))
        assert np.isclose(actual, expected)

    @given(float_no_nan_no_inf())
    def test_if_eq_cases_grouped(self, a):
        b_result_cases = [(1, 1),
                          (3, 1),
                          (4, 1),
                          (-1, 3),
                          (0.5, 3),
                          (-0.5, 1)]

        def reference(a_, b_result_cases_, else_result):
            for b, if_result in b_result_cases_:
                if a_ == b:
                    return if_result
            return else_result

        actual = cas.compile_and_execute(lambda a: cas.if_eq_cases_grouped(a, b_result_cases, 0), [a])
        expected = float(reference(a, b_result_cases, 0))
        assert np.isclose(actual, expected)

    @given(float_no_nan_no_inf(10))
    def test_if_less_eq_cases(self, a):
        b_result_cases = [
            (-1, -1),
            (-0.5, -0.5),
            (0.5, 0.5),
            (1, 1),
            (3, 3),
            (4, 4),
        ]

        def reference(a_, b_result_cases_, else_result):
            for b, if_result in b_result_cases_:
                if a_ <= b:
                    return if_result
            return else_result

        assert np.isclose(
            cas.compile_and_execute(lambda a, default: cas.if_less_eq_cases(a, b_result_cases, default),
                                    [a, 0]),
            float(reference(a, b_result_cases, 0)))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_if_greater(self, a, b, if_result, else_result):
        assert np.isclose(
            cas.compile_and_execute(cas.if_greater, [a, b, if_result, else_result]),
            float(if_result if a > b else else_result))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_if_less(self, a, b, if_result, else_result):
        assert np.isclose(
            cas.compile_and_execute(cas.if_less, [a, b, if_result, else_result]),
            float(if_result if a < b else else_result))

    @given(vector(3),
           vector(3))
    def test_cross(self, u, v):
        assert np.allclose(
            cas.compile_and_execute(cas.cross, [u, v])[:3],
            np.cross(u, v))

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_limit(self, x, lower_limit, upper_limit):
        r1 = cas.compile_and_execute(cas.limit, [x, lower_limit, upper_limit])
        r2 = max(lower_limit, min(upper_limit, x))
        assert np.allclose(r1, r2)

    @given(st.lists(float_no_nan_no_inf(), min_size=1))
    def test_norm(self, v):
        actual = cas.compile_and_execute(cas.norm, [v])
        expected = np.linalg.norm(v)
        assume(not np.isinf(expected))
        assert np.isclose(actual, expected, equal_nan=True)

    @given(vector(3),
           float_no_nan_no_inf())
    def test_scale(self, v, a):
        if np.linalg.norm(v) == 0:
            r2 = [0, 0, 0]
        else:
            r2 = v / np.linalg.norm(v) * a
        assert np.allclose(
            cas.compile_and_execute(cas.scale, [v, a]),
            r2)

    @given(lists_of_same_length([float_no_nan_no_inf(), float_no_nan_no_inf()], max_length=50))
    def test_dot(self, vectors):
        u, v = vectors
        u = np.array(u)
        v = np.array(v)
        result = cas.compile_and_execute(cas.dot, [u, v])
        if not np.isnan(result) and not np.isinf(result):
            assert np.isclose(result, np.dot(u, v))

    @given(lists_of_same_length([float_no_nan_no_inf(outer_limit=1000), float_no_nan_no_inf(outer_limit=1000)],
                                min_length=16, max_length=16))
    def test_dot2(self, vectors):
        u, v = vectors
        u = np.array(u).reshape((4, 4))
        v = np.array(v).reshape((4, 4))
        result = cas.compile_and_execute(cas.dot, [u, v])
        expected = np.dot(u, v)
        if not np.isnan(result).any() and not np.isinf(result).any():
            assert np.allclose(result, expected)

    @given(unit_vector(4))
    def test_trace(self, q):
        m = giskard_math.rotation_matrix_from_quaternion(*q)
        assert np.allclose(cas.compile_and_execute(cas.trace, [m]), np.trace(m))

    @given(quaternion(),
           quaternion())
    def test_rotation_distance(self, q1, q2):
        m1 = giskard_math.rotation_matrix_from_quaternion(*q1)
        m2 = giskard_math.rotation_matrix_from_quaternion(*q2)
        actual_angle = cas.rotational_error(cas.RotationMatrix(m1), cas.RotationMatrix(m2)).to_np()
        _, expected_angle = giskard_math.axis_angle_from_rotation_matrix(m1.T.dot(m2))
        expected_angle = expected_angle
        try:
            assert np.isclose(giskard_math.shortest_angular_distance(actual_angle, expected_angle), 0)
        except AssertionError:
            assert np.isclose(giskard_math.shortest_angular_distance(actual_angle, -expected_angle), 0)

    @given(random_angle(),
           random_angle(),
           random_angle())
    def test_axis_angle_from_rpy(self, roll, pitch, yaw):
        expected_axis, expected_angle = giskard_math.axis_angle_from_rpy(roll, pitch, yaw)
        expected_axis = np.array(list(list(expected_axis)))
        axis = cas.compile_and_execute(lambda r, p, y: cas.axis_angle_from_rpy(r, p, y)[0], [roll, pitch, yaw])
        angle = cas.compile_and_execute(lambda r, p, y: cas.axis_angle_from_rpy(r, p, y)[1], [roll, pitch, yaw])
        compare_axis_angle(angle, axis[:3], expected_angle, expected_axis)
        assert axis[-1] == 0

    @given(quaternion(),
           quaternion(),
           st.floats(allow_nan=False, allow_infinity=False, min_value=0, max_value=1))
    def test_slerp(self, q1, q2, t):
        r1 = cas.compile_and_execute(cas.quaternion_slerp, [q1, q2, t])
        r2 = giskard_math.quaternion_slerp(q1, q2, t)
        assert np.allclose(r1, r2, atol=1e-3) or np.isclose(r1, -r2, atol=1e-3)

    @given(quaternion(),
           quaternion())
    def test_slerp123(self, q1, q2):
        step = 0.1
        q_d = cas.compile_and_execute(lambda q1, q2: cas.Quaternion(q1).diff(cas.Quaternion(q2)),
                                      [q1, q2])
        axis = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[0], q_d)
        angle = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[1], q_d)
        assume(angle != np.pi)
        if np.abs(angle) > np.pi:
            angle = angle - np.pi * 2
        elif np.abs(angle) < -np.pi:
            angle = angle + np.pi * 2
        r1s = []
        r2s = []
        for t in np.arange(0, 1.001, step):
            r1 = cas.compile_and_execute(cas.quaternion_slerp, [q1, q2, t])
            r1 = cas.compile_and_execute(lambda q1, q2: cas.Quaternion(q1).diff(cas.Quaternion(q2)),
                                         [q1, r1])
            axis2 = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[0], r1)
            angle2 = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[1], r1)
            r2 = cas.compile_and_execute(cas.Quaternion.from_axis_angle, [axis, angle * t])
            r1s.append(r1)
            r2s.append(r2)
        aa1 = []
        aa2 = []
        for r1, r2 in zip(r1s, r2s):
            axisr1 = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[0], r1)
            angler1 = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[1], r1)
            aa1.append([axisr1, angler1])
            axisr2 = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[0], r2)
            angler2 = cas.compile_and_execute(lambda x, y, z, w_: cas.Quaternion((x, y, z, w_)).to_axis_angle()[1], r2)
            aa2.append([axisr2, angler2])
        qds = []
        for i in range(len(r1s) - 1):
            q1t = r1s[i]
            q2t = r1s[i + 1]
            qds.append(
                cas.compile_and_execute(lambda q1, q2: cas.Quaternion(q1).diff(cas.Quaternion(q2)),
                                        [q1t, q2t]))
        qds = np.array(qds)
        for r1, r2 in zip(r1s, r2s):
            compare_orientations(r1, r2)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_fmod(self, a, b):
        ref_r = np.fmod(a, b)
        assert np.isclose(cas.compile_and_execute(cas.fmod, [a, b]), ref_r, equal_nan=True)

    @given(float_no_nan_no_inf())
    def test_normalize_angle_positive(self, a):
        expected = giskard_math.normalize_angle_positive(a)
        actual = cas.compile_and_execute(cas.normalize_angle_positive, [a])
        assert np.isclose(giskard_math.shortest_angular_distance(expected, actual), 0.0)

    @given(float_no_nan_no_inf())
    def test_normalize_angle(self, a):
        ref_r = giskard_math.normalize_angle(a)
        assert np.isclose(cas.compile_and_execute(cas.normalize_angle, [a]), ref_r)

    @given(float_no_nan_no_inf(),
           float_no_nan_no_inf())
    def test_shorted_angular_distance(self, angle1, angle2):
        try:
            expected = giskard_math.shortest_angular_distance(angle1, angle2)
        except ValueError:
            expected = np.nan
        actual = cas.compile_and_execute(cas.shortest_angular_distance, [angle1, angle2])
        assert np.isclose(actual, expected, equal_nan=True)

    @given(unit_vector(4),
           unit_vector(4))
    def test_entrywise_product(self, q1, q2):
        m1 = giskard_math.rotation_matrix_from_quaternion(*q1)
        m2 = giskard_math.rotation_matrix_from_quaternion(*q2)
        r1 = cas.compile_and_execute(cas.entrywise_product, [m1, m2])
        r2 = m1 * m2
        assert np.allclose(r1, r2)

    def test_kron(self):
        m1 = np.eye(4)
        r1 = cas.compile_and_execute(cas.kron, [m1, m1])
        r2 = np.kron(m1, m1)
        assert np.allclose(r1, r2)

    @given(sq_matrix())
    def test_sum(self, m):
        actual_sum = cas.compile_and_execute(cas.sum, [m])
        expected_sum = np.sum(m)
        assert np.isclose(actual_sum, expected_sum, rtol=1.e-4)

    @settings(deadline=timedelta(milliseconds=500))
    @given(st.integers(max_value=10000, min_value=1),
           st.integers(max_value=5000, min_value=-5000),
           st.integers(max_value=5000, min_value=-5000),
           st.integers(max_value=1000, min_value=1))
    def test_velocity_limit_from_position_limit(self, acceleration, desired_result, j, step_size):
        step_size /= 1000
        acceleration /= 1000
        desired_result /= 1000
        j /= 1000
        # set current position to 0 such that the desired result is already the difference
        velocity = cas.compile_and_execute(cas.velocity_limit_from_position_limit,
                                           [acceleration, desired_result, j, step_size])
        position = j
        i = 0
        start_sign = np.sign(velocity)
        while np.sign(velocity) == start_sign and i < 100000:
            position += velocity * step_size
            velocity -= np.sign(desired_result - j) * acceleration * step_size
            i += 1
        # np.testing.assert_almost_equal(position, desired_result)
        assert math.isclose(position, desired_result, abs_tol=4, rel_tol=4)

    @given(float_no_nan_no_inf_min_max(min_value=0))
    def test_r_gauss(self, n):
        result = cas.compile_and_execute(lambda x: cas.r_gauss(cas.gauss(x)), [n])
        np.isclose(result, n)
        result = cas.compile_and_execute(lambda x: cas.gauss(cas.r_gauss(x)), [n])
        np.isclose(result, n)

    @given(sq_matrix())
    def test_sum_row(self, m):
        actual_sum = cas.compile_and_execute(cas.sum_row, [m])
        expected_sum = np.sum(m, axis=0)
        assert np.allclose(actual_sum, expected_sum)

    @given(sq_matrix())
    def test_sum_column(self, m):
        actual_sum = cas.compile_and_execute(cas.sum_column, [m])
        expected_sum = np.sum(m, axis=1)
        assert np.allclose(actual_sum, expected_sum)

    def test_distance_point_to_line_segment1(self):
        p = np.array([0, 0, 0])
        start = np.array([0, 0, 0])
        end = np.array([0, 0, 1])
        distance = cas.compile_and_execute(lambda a, b, c: cas.distance_point_to_line_segment(a, b, c)[0],
                                           [p, start, end])
        nearest = cas.compile_and_execute(lambda a, b, c: cas.distance_point_to_line_segment(a, b, c)[1],
                                          [p, start, end])
        assert distance == 0
        assert nearest[0] == 0
        assert nearest[1] == 0
        assert nearest[2] == 0

    def test_distance_point_to_line_segment2(self):
        p = np.array([0, 1, 0.5])
        start = np.array([0, 0, 0])
        end = np.array([0, 0, 1])
        distance = cas.compile_and_execute(lambda a, b, c: cas.distance_point_to_line_segment(a, b, c)[0],
                                           [p, start, end])
        nearest = cas.compile_and_execute(lambda a, b, c: cas.distance_point_to_line_segment(a, b, c)[1],
                                          [p, start, end])
        assert distance == 1
        assert nearest[0] == 0
        assert nearest[1] == 0
        assert nearest[2] == 0.5

    def test_distance_point_to_line_segment3(self):
        p = np.array([0, 1, 2])
        start = np.array([0, 0, 0])
        end = np.array([0, 0, 1])
        distance = cas.compile_and_execute(lambda a, b, c: cas.distance_point_to_line_segment(a, b, c)[0],
                                           [p, start, end])
        nearest = cas.compile_and_execute(lambda a, b, c: cas.distance_point_to_line_segment(a, b, c)[1],
                                          [p, start, end])
        assert distance == 1.4142135623730951
        assert nearest[0] == 0
        assert nearest[1] == 0
        assert nearest[2] == 1

    def test_to_str(self):
        axis = cas.Vector3(cas.create_symbols(['v1', 'v2', 'v3']))
        angle = cas.Symbol('alpha')
        q = cas.Quaternion.from_axis_angle(axis, angle)
        expr = cas.norm(q)
        assert cas.to_str(expr) == [['sqrt((((sq((v1*sin((alpha/2))))'
                                     '+sq((v2*sin((alpha/2)))))'
                                     '+sq((v3*sin((alpha/2)))))'
                                     '+sq(cos((alpha/2)))))']]
        assert cas.to_str(expr) == expr.pretty_str()

    def test_to_str2(self):
        a, b = cas.var('a b')
        e = cas.if_eq(a, 0, a, b)
        assert cas.to_str(e) == [['(((a==0)?a:0)+((!(a==0))?b:0))']]
        assert cas.to_str(e) == e.pretty_str()
