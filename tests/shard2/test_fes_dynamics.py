import re
import pytest
import os

import numpy as np
from bioptim import (
    ObjectiveFcn,
    ObjectiveList,
    Solver,
)

from cocofest import DingModelPulseDurationFrequencyWithFatigue, FESActuatedBiorbdModelOCP

from examples.msk_models import init as ocp_module

biomodel_folder = os.path.dirname(ocp_module.__file__)
biorbd_model_path = biomodel_folder + "/arm26_biceps_triceps.bioMod"


def test_multi_muscle_fes_dynamics():
    objective_functions = ObjectiveList()
    n_stim = 10
    for i in range(n_stim):
        objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_CONTROL, key="tau", weight=1, quadratic=True, phase=i)

    minimum_pulse_duration = DingModelPulseDurationFrequencyWithFatigue().pd0
    ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
        biorbd_model_path=biorbd_model_path,
        bound_type="start_end",
        bound_data=[[0, 5], [0, 120]],
        fes_muscle_models=[
            DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
            DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
        ],
        n_stim=n_stim,
        n_shooting=10,
        final_time=1,
        pulse_duration_min=minimum_pulse_duration,
        pulse_duration_max=0.0006,
        pulse_duration_bimapping=False,
        custom_objective=objective_functions,
        with_residual_torque=True,
        muscle_force_length_relationship=True,
        muscle_force_velocity_relationship=True,
        use_sx=False,
    )

    sol = ocp.solve(Solver.IPOPT(_max_iter=1000)).merge_phases()

    np.testing.assert_almost_equal(sol.cost, 2.64645e-08)
    np.testing.assert_almost_equal(
        sol.parameters["pulse_duration_BIClong"],
        np.array(
            [
                [0.00059638],
                [0.00059498],
                [0.00059357],
                [0.00059024],
                [0.00058198],
                [0.00054575],
                [0.00014772],
                [0.00015474],
                [0.00018023],
                [0.00029466],
            ]
        ),
    )
    np.testing.assert_almost_equal(
        sol.parameters["pulse_duration_TRIlong"],
        np.array(
            [
                [0.00015802],
                [0.00015879],
                [0.00052871],
                [0.00055611],
                [0.00028161],
                [0.00013942],
                [0.00014098],
                [0.00014026],
                [0.00014371],
                [0.00019614],
            ]
        ),
    )

    np.testing.assert_almost_equal(sol.states["q"][0][0], 0)
    np.testing.assert_almost_equal(sol.states["q"][0][-1], 0)
    np.testing.assert_almost_equal(sol.states["q"][1][0], 0.08722222222222223)
    np.testing.assert_almost_equal(sol.states["q"][1][-1], 2.0933333333333333)
    np.testing.assert_almost_equal(sol.states["F_BIClong"][0][-1], 33.20686595)
    np.testing.assert_almost_equal(sol.states["F_TRIlong"][0][-1], 18.36373478)


def test_fes_models_inputs_sanity_check_errors():
    with pytest.raises(
        TypeError,
        match=re.escape("biorbd_model_path should be a string"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=5,
            bound_type="start_end",
            bound_data=[[0, 5], [0, 120]],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        ValueError,
        match=re.escape("bound_type should be a string and should be equal to start, end or start_end"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="hello",
            bound_data=[[0, 5], [0, 120]],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        TypeError,
        match=re.escape("bound_data should be a list"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start_end",
            bound_data="[[0, 5], [0, 120]]",
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        ValueError,
        match=re.escape(f"bound_data should be a list of {2} elements"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start_end",
            bound_data=[[0, 5, 7], [0, 120, 150]],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"bound_data should be a list of two list"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start_end",
            bound_data=["[0, 5]", [0, 120]],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        ValueError,
        match=re.escape(f"bound_data should be a list of {2} elements"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start_end",
            bound_data=[[0, 5, 7], [0, 120, 150]],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"bound data index {1}: {5} and {'120'} should be an int or float"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start_end",
            bound_data=[[0, 5], [0, "120"]],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        ValueError,
        match=re.escape(f"bound_data should be a list of {2} element"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5, 10],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"bound data index {1}: {'5'} should be an int or float"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="end",
            bound_data=[0, "5"],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        TypeError,
        match=re.escape(
            "model must be a DingModelFrequency,"
            " DingModelFrequencyWithFatigue,"
            " DingModelPulseDurationFrequency,"
            " DingModelPulseDurationFrequencyWithFatigue,"
            " DingModelIntensityFrequency,"
            " DingModelIntensityFrequencyWithFatigue type"
        ),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                "DingModelPulseDurationFrequencyWithFatigue(muscle_name='TRIlong')",
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"force_tracking: {'hello'} must be list type"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            force_tracking="hello",
        )

    with pytest.raises(
        ValueError,
        match=re.escape("force_tracking must of size 2"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="end",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            force_tracking=["hello"],
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"force_tracking index 0: {'hello'} must be np.ndarray type"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            force_tracking=["hello", [1, 2, 3]],
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"force_tracking index 1: {'[1, 2, 3]'} must be list type"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            force_tracking=[np.array([1, 2, 3]), "[1, 2, 3]"],
        )

    with pytest.raises(
        ValueError,
        match=re.escape(
            "force_tracking index 1 list must have the same size as the number of muscles in fes_muscle_models"
        ),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            force_tracking=[np.array([1, 2, 3]), [[1, 2, 3], [1, 2, 3], [1, 2, 3]]],
        )

    with pytest.raises(
        ValueError,
        match=re.escape("force_tracking time and force argument must be the same length"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            force_tracking=[np.array([1, 2, 3]), [[1, 2, 3], [1, 2]]],
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"force_tracking: {'hello'} must be list type"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            end_node_tracking="hello",
        )

    with pytest.raises(
        ValueError,
        match=re.escape("end_node_tracking list must have the same size as the number of muscles in fes_muscle_models"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            end_node_tracking=[2, 3, 4],
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"end_node_tracking index {1}: {'hello'} must be int or float type"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            end_node_tracking=[2, "hello"],
        )

    with pytest.raises(
        TypeError,
        match=re.escape("q_tracking should be a list of size 2"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            q_tracking="hello",
        )

    with pytest.raises(
        ValueError,
        match=re.escape("q_tracking[0] should be a list"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            q_tracking=["hello", [1, 2, 3]],
        )

    with pytest.raises(
        ValueError,
        match=re.escape("q_tracking[1] should have the same size as the number of generalized coordinates"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            q_tracking=[[1, 2, 3], [1, 2, 3]],
        )

    with pytest.raises(
        ValueError,
        match=re.escape("q_tracking[0] and q_tracking[1] should have the same size"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            q_tracking=[[1, 2, 3], [[1, 2, 3], [4, 5]]],
        )

    with pytest.raises(
        TypeError,
        match=re.escape(f"{'with_residual_torque'} should be a boolean"),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong"),
                DingModelPulseDurationFrequencyWithFatigue(muscle_name="TRIlong"),
            ],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
            with_residual_torque="hello",
        )


def test_fes_muscle_models_sanity_check_errors():
    with pytest.raises(
        ValueError,
        match=re.escape(
            f"The muscle {'TRIlong'} is not in the fes muscle model "
            f"please add it into the fes_muscle_models list by providing the muscle_name ="
            f" {'TRIlong'}"
        ),
    ):
        ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
            biorbd_model_path=biorbd_model_path,
            bound_type="start",
            bound_data=[0, 5],
            fes_muscle_models=[DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong")],
            n_stim=1,
            n_shooting=10,
            final_time=1,
            pulse_duration_min=0.0003,
            pulse_duration_max=0.0006,
        )
