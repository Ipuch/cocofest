"""
This example will do an optimal control program of a 100 steps hand cycling motion with either a torque driven /
muscle driven / FES driven dynamics and includes a resistive torque at the handle.
"""

import numpy as np

from bioptim import (
    Axis,
    BiorbdModel,
    BoundsList,
    ConstraintList,
    ConstraintFcn,
    ControlType,
    CostType,
    DynamicsFcn,
    DynamicsList,
    ExternalForceSetTimeSeries,
    InitialGuessList,
    InterpolationType,
    Node,
    ObjectiveFcn,
    ObjectiveList,
    OdeSolver,
    OptimalControlProgram,
    ParameterList,
    PhaseDynamics,
    Solver,
    ParameterObjectiveList,
)

from cocofest import (
    CustomObjective,
    DingModelPulseWidthFrequencyWithFatigue,
    FesMskModel,
    inverse_kinematics_cycling,
    OcpFesMsk,
    FES_plot,
    OcpFes,
    DingModelPulseWidthFrequency,
)


def prepare_ocp(
    model: BiorbdModel | FesMskModel,
    n_shooting: int,
    final_time: int,
    turn_number: int,
    pedal_config: dict,
    pulse_width: dict,
    dynamics_type: str = "torque_driven",
    use_sx: bool = True,
    control_type: ControlType = ControlType.CONSTANT,
    integration_step: int = 1,
) -> OptimalControlProgram:
    """
    Prepare the optimal control program (OCP) with the provided configuration.

    Parameters
    ----------
    model: BiorbdModel | FesMskModel
        The biomechanical model.
    n_shooting: int
        Number of shooting nodes.
    final_time: int
        Total time of the motion.
    turn_number: int
        Number of complete turns.
    pedal_config: dict
        Dictionary with pedal configuration (e.g., center and radius).
    pulse_width: dict
        Dictionary with pulse width parameters for FES-driven dynamics.
    dynamics_type: str
        Type of dynamics ("torque_driven", "muscle_driven", or "fes_driven").
    use_sx: bool
        Whether to use CasADi SX for symbolic computations.
    integration_step: int
        Integration step for the ODE solver.

    Returns
    -------
        An OptimalControlProgram instance configured for the problem.
    """
    # Set external forces (e.g., resistive torque at the handle)
    numerical_time_series, external_force_set = set_external_forces(n_shooting, torque=-1)

    # Set stimulation time in numerical_data_time_series
    if isinstance(model, FesMskModel):
        numerical_data_time_series, stim_idx_at_node_list = model.muscles_dynamics_model[
            0
        ].get_numerical_data_time_series(n_shooting, final_time)
        numerical_time_series.update(numerical_data_time_series)

    # Set dynamics based on the chosen dynamics type
    dynamics = set_dynamics(model, numerical_time_series, dynamics_type_str=dynamics_type)
    # Configure objective functions
    objective_functions = set_objective_functions(model, dynamics_type)
    # Set initial guess for state variables
    x_init = set_x_init(n_shooting, pedal_config, turn_number)
    # Define state bounds
    x_bounds = set_state_bounds(
        model=model,
        x_init=x_init,
        n_shooting=n_shooting,
        turn_number=turn_number,
        interpolation_type=InterpolationType.EACH_FRAME,
        cardinal=2,
    )
    # Define control bounds and initial guess
    u_init, u_bounds = set_u_bounds_and_init(model, dynamics_type_str=dynamics_type)

    # Set constraints
    constraints = set_constraints(model, n_shooting, turn_number)

    parameters = ParameterList(use_sx=use_sx)
    parameters_bounds = BoundsList()
    parameters_init = InitialGuessList()
    parameter_objectives = ParameterObjectiveList()

    # Update the model with external forces and parameters
    model = update_model(model, external_force_set, parameters)

    return OptimalControlProgram(
        [model],
        dynamics,
        n_shooting,
        final_time,
        x_bounds=x_bounds,
        u_bounds=u_bounds,
        x_init=x_init,
        u_init=u_init,
        objective_functions=objective_functions,
        ode_solver=OdeSolver.RK4(n_integration_steps=integration_step),
        n_threads=20,
        constraints=constraints,
        parameters=parameters,
        parameter_bounds=parameters_bounds,
        parameter_init=parameters_init,
        parameter_objectives=parameter_objectives,
        use_sx=use_sx,
        control_type=control_type,
    )


def set_external_forces(n_shooting: int, torque: int | float) -> tuple[dict, ExternalForceSetTimeSeries]:
    """
    Create an external force time series applying a constant torque.

    Parameters
    ----------
        n_shooting: int
            Number of shooting nodes.
        torque: int | float
            Torque value to be applied.

    Returns
    -------
        A tuple with a numerical time series dictionary and the ExternalForceSetTimeSeries object.
    """
    external_force_set = ExternalForceSetTimeSeries(nb_frames=n_shooting)
    external_force_array = np.array([0, 0, torque])
    reshape_values_array = np.tile(external_force_array[:, np.newaxis], (1, n_shooting))
    external_force_set.add_torque(segment="wheel", values=reshape_values_array)
    numerical_time_series = {"external_forces": external_force_set.to_numerical_time_series()}
    return numerical_time_series, external_force_set


def update_model(
    model: BiorbdModel | FesMskModel, external_force_set: ExternalForceSetTimeSeries, parameters: ParameterList = None
) -> BiorbdModel | FesMskModel:
    """
    Update the model with external forces and parameters if necessary.

    Parameters
    ----------
    model: BiorbdModel | FesMskModel
        The initial model.
    external_force_set: ExternalForceSetTimeSeries
        The external forces to be applied.
    parameters: ParameterList
        Optional parameters for the FES model.

    Returns
    -------
    Updated model instance.
    """
    if isinstance(model, FesMskModel):
        model = FesMskModel(
            name=model.name,
            biorbd_path=model.biorbd_path,
            muscles_model=model.muscles_dynamics_model,
            stim_time=model.muscles_dynamics_model[0].stim_time,
            previous_stim=model.muscles_dynamics_model[0].previous_stim,
            activate_force_length_relationship=model.activate_force_length_relationship,
            activate_force_velocity_relationship=model.activate_force_velocity_relationship,
            activate_residual_torque=model.activate_residual_torque,
            parameters=parameters,
            external_force_set=external_force_set,
        )
    else:
        model = BiorbdModel(model.path, external_force_set=external_force_set)

    return model


def set_dynamics(
    model: BiorbdModel | FesMskModel, numerical_time_series: dict, dynamics_type_str: str = "torque_driven"
) -> DynamicsList:
    """
    Set the dynamics of the optimal control program based on the chosen dynamics type.

    Parameters
    ----------
    model: BiorbdModel | FesMskModel
        The biomechanical model.
    numerical_time_series: dict
        External numerical data (e.g., external forces).
    dynamics_type_str: str
        Type of dynamics ("torque_driven", "muscle_driven", or "fes_driven").

    Returns
    -------
        A DynamicsList configured for the problem.
    """
    dynamics_type = (
        DynamicsFcn.TORQUE_DRIVEN
        if dynamics_type_str == "torque_driven"
        else (
            DynamicsFcn.MUSCLE_DRIVEN
            if dynamics_type_str == "muscle_driven"
            else model.declare_model_variables if dynamics_type_str == "fes_driven" else None
        )
    )
    if dynamics_type is None:
        raise ValueError("Dynamics type not recognized")

    dynamics = DynamicsList()
    dynamics.add(
        dynamics_type=dynamics_type,
        dynamic_function=(
            None if dynamics_type in (DynamicsFcn.TORQUE_DRIVEN, DynamicsFcn.MUSCLE_DRIVEN) else model.muscle_dynamic
        ),
        expand_dynamics=True,
        expand_continuity=False,
        phase_dynamics=PhaseDynamics.SHARED_DURING_THE_PHASE,
        numerical_data_timeseries=numerical_time_series,
        with_contact=True,
        phase=0,
    )
    return dynamics


def set_objective_functions(model: BiorbdModel | FesMskModel, dynamics_type: str) -> ObjectiveList:
    """
    Configure the objective functions for the optimal control problem.

    Parameters
    ----------
    model: BiorbdModel | FesMskModel
        The biomechanical model.
    dynamics_type: str
        The type of dynamics used.

    Returns
    -------
    An ObjectiveList with the appropriate objectives.
    """
    objective_functions = ObjectiveList()
    if isinstance(model, FesMskModel):
        objective_functions.add(
            CustomObjective.minimize_overall_muscle_force_production,
            custom_type=ObjectiveFcn.Lagrange,
            weight=1,
            quadratic=True,
        )
        # Uncomment these following lines if muscle fatigue minimization is desired:
        # objective_functions.add(
        #   CustomObjective.minimize_overall_muscle_fatigue,
        #   custom_type=ObjectiveFcn.Lagrange,
        #   weight=1,
        #   quadratic=True)
    else:
        control_key = "tau" if dynamics_type == "torque_driven" else "muscles"
        objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_CONTROL, key=control_key, weight=1000, quadratic=True)
    return objective_functions


def set_x_init(n_shooting: int, pedal_config: dict, turn_number: int) -> InitialGuessList:
    """
    Set the initial guess for the state variables based on inverse kinematics.

    Parameters
    ----------
    n_shooting: int
        Number of shooting nodes.
    pedal_config: dict
        Dictionary with keys "x_center", "y_center", and "radius".
    turn_number: int
        Number of complete turns.

    Returns
    -------
    An InitialGuessList for the state variables.
    """
    x_init = InitialGuessList()
    # Path to the biomechanical model used for inverse kinematics
    biorbd_model_path = "../../msk_models/simplified_UL_Seth_pedal_aligned_for_inverse_kinematics.bioMod"
    q_guess, qdot_guess, qddotguess = inverse_kinematics_cycling(
        biorbd_model_path,
        n_shooting,
        x_center=pedal_config["x_center"],
        y_center=pedal_config["y_center"],
        radius=pedal_config["radius"],
        ik_method="lm",
        cycling_number=turn_number,
    )
    x_init.add("q", q_guess, interpolation=InterpolationType.EACH_FRAME)
    # Optionally, add qdot initialization if needed:
    # x_init.add("qdot", qdot_guess, interpolation=InterpolationType.EACH_FRAME)

    # Optional, method to get control initial guess:
    # u_guess = inverse_dynamics_cycling(biorbd_model_path, q_guess, qdot_guess, qddotguess)
    # u_init.add("tau", u_guess, interpolation=InterpolationType.EACH_FRAME)

    return x_init


def set_u_bounds_and_init(
    model: BiorbdModel | FesMskModel, dynamics_type_str: str
) -> tuple[InitialGuessList, BoundsList]:
    """
    Define the control bounds and initial guess for the optimal control problem.

    Parameters
    ----------
    model: BiorbdModel | FesMskModel
        The biomechanical model.
    dynamics_type_str: str
        Type of dynamics ("torque_driven" or "muscle_driven").

    Returns
    -------
    A tuple containing the initial guess list for controls and the bounds list.
    """
    u_bounds = BoundsList()
    u_init = InitialGuessList()
    if dynamics_type_str == "torque_driven":
        u_bounds.add(key="tau", min_bound=np.array([-50, -50, -0]), max_bound=np.array([50, 50, 0]), phase=0)
    elif dynamics_type_str == "muscle_driven":
        muscle_min, muscle_max, muscle_init = 0.0, 1.0, 0.5
        u_bounds.add(
            key="muscles",
            min_bound=np.array([muscle_min] * model.nb_muscles),
            max_bound=np.array([muscle_max] * model.nb_muscles),
            phase=0,
        )
        u_init.add(key="muscles", initial_guess=np.array([muscle_init] * model.nb_muscles), phase=0)
    elif dynamics_type_str == "fes_driven":
        if isinstance(model.muscles_dynamics_model[0], DingModelPulseWidthFrequency):
            for model in model.muscles_dynamics_model:
                key = "last_pulse_width_" + str(model.muscle_name)
                u_init.add(key=key, initial_guess=[0], phase=0)
                u_bounds.add(key=key, min_bound=[model.pd0], max_bound=[0.0006], phase=0)

    return u_init, u_bounds


def set_state_bounds(
    model: BiorbdModel | FesMskModel,
    x_init: InitialGuessList,
    n_shooting: int,
    turn_number: int,
    interpolation_type: InterpolationType = InterpolationType.CONSTANT,
    cardinal: int = 4,
) -> BoundsList:
    """
    Set the bounds for the state variables.

    Parameters
    ----------
    model: BiorbdModel | FesMskModel
        The biomechanical model.
    x_init: InitialGuessList
        Initial guess for states.
    n_shooting: int
        Number of shooting nodes.
    turn_number: int
        Number of complete turns.
    interpolation_type: InterpolationType
        Interpolation type for the bounds.
    cardinal: int
        Number of cardinal nodes per turn for bounds adjustment.

    Returns
    -------
    A BoundsList object with the defined state bounds.
    """
    x_bounds = BoundsList()
    # For FES models, retrieve custom bounds
    if isinstance(model, FesMskModel):
        x_bounds, _ = OcpFesMsk._set_bounds_fes(model)

    # Retrieve default bounds from the model for positions and velocities
    q_x_bounds = model.bounds_from_ranges("q")
    qdot_x_bounds = model.bounds_from_ranges("qdot")

    if interpolation_type == InterpolationType.EACH_FRAME:
        # Replicate bounds for each shooting node
        x_min_bound = []
        x_max_bound = []
        for i in range(q_x_bounds.min.shape[0]):
            x_min_bound.append([q_x_bounds.min[i][0]] * (n_shooting + 1))
            x_max_bound.append([q_x_bounds.max[i][0]] * (n_shooting + 1))

        # Adjust bounds at cardinal nodes for a specific coordinate (e.g., index 2)
        cardinal_node_list = [
            i * int(n_shooting / ((n_shooting / (n_shooting / turn_number)) * cardinal))
            for i in range(int((n_shooting / (n_shooting / turn_number)) * cardinal + 1))
        ]
        slack = 10 * (np.pi / 180)
        for i in range(len(x_min_bound[0])):
            x_min_bound[0][i] = 0
            x_max_bound[0][i] = 1
            x_min_bound[1][i] = 1
            x_min_bound[2][i] = x_init["q"].init[2][-1]
            x_max_bound[2][i] = x_init["q"].init[2][0]
        for i in range(len(cardinal_node_list)):
            cardinal_index = cardinal_node_list[i]
            x_min_bound[2][cardinal_index] = (
                x_init["q"].init[2][cardinal_index]
                if i % cardinal == 0
                else x_init["q"].init[2][cardinal_index] - slack
            )
            x_max_bound[2][cardinal_index] = (
                x_init["q"].init[2][cardinal_index]
                if i % cardinal == 0
                else x_init["q"].init[2][cardinal_index] + slack
            )
            # x_min_bound[2][cardinal_index] = x_init["q"].init[2][cardinal_index] - slack
            # x_max_bound[2][cardinal_index] = x_init["q"].init[2][cardinal_index] + slack

        x_bounds.add(
            key="q", min_bound=x_min_bound, max_bound=x_max_bound, phase=0, interpolation=InterpolationType.EACH_FRAME
        )

    else:
        x_bounds.add(key="q", bounds=q_x_bounds, phase=0)

    # Modify bounds for velocities (e.g., setting maximum pedal speed to 0 to prevent the pedal to go backward)
    qdot_x_bounds.max[0] = [10, 10, 10]
    qdot_x_bounds.min[0] = [-10, -10, -10]
    qdot_x_bounds.max[1] = [10, 10, 10]
    qdot_x_bounds.min[1] = [-10, -10, -10]
    qdot_x_bounds.max[2] = [-1, -1, -1]
    # qdot_x_bounds.max[2] = [0, 0, 0]
    # qdot_x_bounds.min[2] = [-14, -14, -14]
    x_bounds.add(key="qdot", bounds=qdot_x_bounds, phase=0)
    return x_bounds


def set_constraints(model: BiorbdModel | FesMskModel, n_shooting: int, turn_number: int) -> ConstraintList:
    """
    Set constraints for the optimal control problem.

    Parameters
    ----------
    model: BiorbdModel | FesMskModel
        The biomechanical model.
    n_shooting: int
        Number of shooting nodes.
    turn_number: int
        Number of complete turns.

    Returns
    -------
        A ConstraintList with the defined constraints.
    """
    constraints = ConstraintList()
    constraints.add(
        ConstraintFcn.TRACK_MARKERS_VELOCITY,
        node=Node.START,
        marker_index=model.marker_index("wheel_center"),
        axes=[Axis.X, Axis.Y],
    )

    superimpose_marker_list = [
        i * int(n_shooting / ((n_shooting / (n_shooting / turn_number)) * 1))
        for i in range(int((n_shooting / (n_shooting / turn_number)) * 1 + 1))
    ]
    for i in superimpose_marker_list:
        constraints.add(
            ConstraintFcn.SUPERIMPOSE_MARKERS,
            first_marker="wheel_center",
            second_marker="global_wheel_center",
            node=i,
            axes=[Axis.X, Axis.Y],
        )

    return constraints


def main():
    """
    Main function to configure and solve the optimal control problem.
    """
    # --- Configuration --- #
    dynamics_type = "fes_driven"  # Available options: "torque_driven", "muscle_driven", "fes_driven"
    # dynamics_type = "torque_driven"
    model_path = "../../msk_models/simplified_UL_Seth_pedal_aligned.bioMod"
    pulse_width = None
    final_time = 1
    n_shooting = 100 * final_time
    turn_number = final_time
    pedal_config = {"x_center": 0.35, "y_center": 0.0, "radius": 0.1}

    # --- Load the appropriate model --- #
    if dynamics_type in ["torque_driven", "muscle_driven"]:
        model = BiorbdModel(model_path)
        integration_step = 1
    elif dynamics_type == "fes_driven":
        # Define muscle dynamics for the FES-driven model
        muscles_model = [
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="DeltoideusClavicle_A", sum_stim_truncation=10),
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="DeltoideusScapula_P", sum_stim_truncation=10),
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="TRIlong", sum_stim_truncation=10),
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="BIC_long", sum_stim_truncation=10),
            DingModelPulseWidthFrequencyWithFatigue(muscle_name="BIC_brevis", sum_stim_truncation=10),
        ]
        stim_time = list(np.linspace(0, final_time, 34)[:-1])
        model = FesMskModel(
            name=None,
            biorbd_path=model_path,
            muscles_model=muscles_model,
            stim_time=stim_time,
            activate_force_length_relationship=True,
            activate_force_velocity_relationship=True,
            activate_passive_force_relationship=True,
            activate_residual_torque=False,
            external_force_set=None,  # External forces will be added later
        )
        pulse_width = {
            "min": DingModelPulseWidthFrequencyWithFatigue().pd0,
            "max": 0.0006,
            "bimapping": False,
            "same_for_all_muscles": False,
            "fixed": False,
        }
        # Adjust n_shooting based on the stimulation time
        n_shooting = OcpFes.prepare_n_shooting(stim_time, final_time)
        integration_step = 5
    else:
        raise ValueError(f"Dynamics type '{dynamics_type}' not recognized")

    ocp = prepare_ocp(
        model=model,
        n_shooting=n_shooting,
        final_time=final_time,
        turn_number=turn_number,
        pedal_config=pedal_config,
        pulse_width=pulse_width,
        dynamics_type=dynamics_type,
        use_sx=True,
        integration_step=integration_step,
    )
    # Add the penalty cost function plot
    ocp.add_plot_penalty(CostType.ALL)
    # Solve the optimal control problem
    sol = ocp.solve(Solver.IPOPT(show_online_optim=False, _max_iter=1000))
    # Display graphs and animate the solution

    sol.graphs(show_bounds=True)

    # if dynamics_type == "fes_driven":
    #     FES_plot(data=sol).plot(title="FES-driven cycling")
    # else:
    #     sol.graphs(show_bounds=True)
    # sol.animate(viewer="pyorerun")


if __name__ == "__main__":
    main()
