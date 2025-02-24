import math
import numpy as np
from scipy.interpolate import interp1d

import biorbd


# This function gets the x, y, z circle coordinates based on the angle theta
def get_circle_coord(
    theta: int | float,
    x_center: int | float,
    y_center: int | float,
    radius: int | float,
    z: int | float = None,
) -> list:
    """
    Get the x, y, z coordinates of a circle based on the angle theta and the center of the circle

    Parameters
    ----------
    theta: int | float
        The angle of the circle in radians
    x_center: int | float
        The x coordinate of the center of the circle
    y_center: int | float
        The y coordinate of the center of the circle
    radius: int | float
        The radius of the circle
    z: int | float
        The z coordinate of the center of the circle. If None, the z coordinate of the circle will be 0

    Returns
    ----------
    x, y, z : list
        The x, y, z coordinates of the circle

    """
    x = radius * math.cos(theta) + x_center
    y = radius * math.sin(theta) + y_center
    if z is None:
        return [x, y, 0]
    else:
        return [x, y, z]


# This function gives the inverse kinematics q of a cycling movement for a given model
def inverse_kinematics_cycling(
    model_path: str,
    n_shooting: int,
    x_center: int | float,
    y_center: int | float,
    radius: int | float,
    ik_method: str = "trf",
    cycling_number: int = 1,
) -> tuple:
    """
    Perform the inverse kinematics of a cycling movement

    Parameters
    ----------
    model_path: str
        The path to the model
    n_shooting: int
        The number of shooting points
    x_center: int | float
        The x coordinate of the center of the circle
    y_center: int | float
        The y coordinate of the center of the circle
    radius: int | float
        The radius of the circle
    ik_method: str
        The method to solve the inverse kinematics problem
        If ik_method = 'lm', the 'trf' method will be used for the first frame, in order to respect the bounds of the model.
        Then, the 'lm' method will be used for the following frames.
        If ik_method = 'trf', the 'trf' method will be used for all the frames.
        If ik_method = 'only_lm', the 'lm' method will be used for all the frames.

        In least_square:
            -‘trf’ : Trust Region Reflective algorithm, particularly suitable for large sparse problems
                    with bounds.
                    Generally robust method.
            -‘lm’ : Levenberg-Marquardt algorithm as implemented in MINPACK.
                    Does not handle bounds and sparse Jacobians.
                    Usually the most efficient method for small unconstrained problems.
    cycling_number: int
        The number of cycle performed in a single problem

    Returns
    ----------
    q : np.array
        joints angles
    """

    model = biorbd.Model(model_path)

    z = model.markers(np.array([0] * model.nbQ()))[0].to_array()[2]
    if z != model.markers(np.array([np.pi / 2] * model.nbQ()))[0].to_array()[2]:
        print("The model not strictly 2d. Warm start not optimal.")

    f = interp1d(
        np.linspace(0, -360 * cycling_number, 360 * cycling_number + 1),
        np.linspace(0, -360 * cycling_number, 360 * cycling_number + 1),
        kind="linear",
    )
    x_new = f(np.linspace(0, -360 * cycling_number, n_shooting + 1))
    x_new_rad = np.deg2rad(x_new)

    x_y_z_coord = np.array([get_circle_coord(theta, x_center, y_center, radius) for theta in x_new_rad]).T

    target_q_hand = x_y_z_coord.reshape((3, 1, n_shooting + 1))  # Hand marker_target
    wheel_center_x_y_z_coord = np.array([x_center, y_center, z])
    target_q_wheel_center = np.tile(
        wheel_center_x_y_z_coord[:, np.newaxis, np.newaxis], (1, 1, n_shooting + 1)
    )  # Wheel marker_target
    target_q = np.concatenate((target_q_hand, target_q_wheel_center), axis=1)
    ik = biorbd.InverseKinematics(model, target_q)
    ik_q = ik.solve(method=ik_method)
    ik_qdot = np.array([np.gradient(ik_q[i], (1 / n_shooting)) for i in range(ik_q.shape[0])])
    ik_qddot = np.array([np.gradient(ik_qdot[i], (1 / n_shooting)) for i in range(ik_qdot.shape[0])])
    return ik_q, ik_qdot, ik_qddot


# This function gives the inverse dynamics Tau of a cycling motion for a given model and q, qdot, qddot
def inverse_dynamics_cycling(
    model_path: str,
    q: np.array,
    qdot: np.array,
    qddot: np.array,
) -> np.array:
    """
    Perform the inverse dynamics of a cycling movement

    Parameters
    ----------
    model_path: str
        The path to the used model
    q: np.array
        joints angles
    qdot: np.array
        joints velocities
    qddot: np.array
        joints accelerations

    Returns
    ----------
    Tau : np.array
        joints torques
    """
    model = biorbd.Model(model_path)
    tau_shape = (model.nbQ(), q.shape[1])
    tau = np.zeros(tau_shape)
    for i in range(tau.shape[1]):
        tau_i = model.InverseDynamics(q[:, i], qdot[:, i], qddot[:, i])
        tau[:, i] = tau_i.to_array()
    return tau[:, :-1]
