"""
This example will do an optimal control program of a 10 stimulation example with Ding's 2007 pulse width model.
Those ocp were build to produce a cycling motion.
The stimulation frequency will be set to 10Hz and pulse width will be optimized to satisfy the motion meanwhile
reducing residual torque.
"""

import numpy as np

from bioptim import CostType, Solver

import biorbd

from cocofest import (
    DingModelPulseWidthFrequencyWithFatigue,
    OcpFesMsk,
    PlotCyclingResult,
    SolutionToPickle,
    FesMskModel,
    PickleAnimate,
)


def main():
    minimum_pulse_width = DingModelPulseWidthFrequencyWithFatigue().pd0

    model = FesMskModel(
        name=None,
        biorbd_path="../../msk_models/simplified_UL_Seth.bioMod",
        muscles_model=[
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="DeltoideusClavicle_A"),
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="DeltoideusScapula_P"),
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="TRIlong"),
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="BIC_long"),
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="BIC_brevis"),
        ],
        activate_force_length_relationship=True,
        activate_force_velocity_relationship=True,
        activate_residual_torque=True,
    )

    ocp = OcpFesMsk.prepare_ocp(
        model=model,
        stim_time=list(np.round(np.linspace(0, 1, 11), 3))[:-1],
        final_time=1,
        pulse_width={
            "min": minimum_pulse_width,
            "max": 0.0006,
            "bimapping": False,
        },
        msk_info={"with_residual_torque": True},
        objective={
            "cycling": {"x_center": 0.35, "y_center": 0, "radius": 0.1, "target": "marker"},
            "minimize_residual_torque": True,
        },
        initial_guess_warm_start=False,
        n_threads=5,
    )
    ocp.add_plot_penalty(CostType.ALL)
    sol = ocp.solve(Solver.IPOPT(show_online_optim=False, _max_iter=10000))
    SolutionToPickle(sol, "cycling_fes_driven_min_residual_torque.pkl", "").pickle()

    biorbd_model = biorbd.Model("../../msk_models/simplified_UL_Seth_full_mesh.bioMod")
    PickleAnimate("cycling_fes_driven_min_residual_torque.pkl").animate(model=biorbd_model)

    sol.graphs(show_bounds=False)
    PlotCyclingResult(sol).plot(starting_location="E")


if __name__ == "__main__":
    main()
