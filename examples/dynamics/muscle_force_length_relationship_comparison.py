"""
This example will do a 10 stimulation example with Ding's 2003 frequency model associated to Bakir's 2022 intensity work.
Those ocp were build to move the elbow starting from 0 degrees angle.
The stimulation frequency will be set to 10Hz and intensity to 40mA.
No residual torque is allowed.
"""
import matplotlib.pyplot as plt

from bioptim import Solver

from cocofest import (
    DingModelPulseDurationFrequencyWithFatigue,
    DingModelIntensityFrequencyWithFatigue,
    FESActuatedBiorbdModelOCP,
)

minimum_pulse_duration = DingModelPulseDurationFrequencyWithFatigue().pd0
minimum_pulse_intensity = DingModelIntensityFrequencyWithFatigue.min_pulse_intensity(
    DingModelIntensityFrequencyWithFatigue()
)

sol_list = []
muscle_force_length_relationship = [False, True, False, True]
fes_muscle_model = [
    [DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong")],
    [DingModelPulseDurationFrequencyWithFatigue(muscle_name="BIClong")],
    [DingModelIntensityFrequencyWithFatigue(muscle_name="BIClong")],
    [DingModelIntensityFrequencyWithFatigue(muscle_name="BIClong")],
]

for i in range(4):
    ocp = FESActuatedBiorbdModelOCP.prepare_ocp(
        biorbd_model_path="/arm26_biceps_1dof.bioMod",
        bound_type="start",
        bound_data=[0],
        fes_muscle_models=fes_muscle_model[i],
        n_stim=10,
        n_shooting=10,
        final_time=1,
        pulse_duration=0.00026,
        pulse_intensity=40,
        with_residual_torque=False,
        muscle_force_length_relationship=muscle_force_length_relationship[i],
        muscle_force_velocity_relationship=False,
        use_sx=False,
    )
    sol = ocp.solve(Solver.IPOPT(_max_iter=1000))
    sol_list.append(sol.merge_phases())

plt.title(
    "Comparison between with and without muscle force length relationship for an elbow movement at 10Hz and 40mA or 260us"
)
plt.plot(sol_list[0].time, sol_list[0].states["q"][0], label="Pulse duration without force length relationship")
plt.plot(sol_list[1].time, sol_list[1].states["q"][0], label="Pulse duration with force length relationship")
plt.plot(sol_list[2].time, sol_list[2].states["q"][0], label="Pulse intensity without force length relationship")
plt.plot(sol_list[3].time, sol_list[3].states["q"][0], label="Pulse intensity with force length relationship")

plt.xlabel("Time (s)")
plt.ylabel("Angle (rad)")
plt.legend()
plt.show()
