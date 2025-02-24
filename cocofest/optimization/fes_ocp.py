import numpy as np
from math import gcd
from fractions import Fraction

from bioptim import (
    BoundsList,
    ConstraintList,
    ControlType,
    DynamicsList,
    InitialGuessList,
    InterpolationType,
    Node,
    Objective,
    ObjectiveFcn,
    ObjectiveList,
    OdeSolver,
    OptimalControlProgram,
    ParameterList,
    ParameterObjectiveList,
    PhaseDynamics,
    VariableScaling,
)

from ..fourier_approx import FourierSeries
from ..models.fes_model import FesModel
from ..models.dynamical_model import FesMskModel
from ..models.ding2007 import DingModelPulseWidthFrequency
from ..models.hmed2018 import DingModelPulseIntensityFrequency
from ..custom_constraints import CustomConstraint


class OcpFes:
    """
    The main class to define an ocp. This class prepares the full program and gives all
    the needed parameters to solve a functional electrical stimulation ocp.
    """

    @staticmethod
    def _prepare_optimization_problem(input_dict: dict) -> dict:

        (pulse_width, pulse_intensity, objective) = OcpFes._fill_dict(
            input_dict["pulse_width"],
            input_dict["pulse_intensity"],
            input_dict["objective"],
        )

        OcpFes._sanity_check(
            model=input_dict["model"],
            n_shooting=input_dict["n_shooting"],
            final_time=input_dict["final_time"],
            objective=objective,
            use_sx=input_dict["use_sx"],
            ode_solver=input_dict["ode_solver"],
            n_threads=input_dict["n_threads"],
        )

        (parameters, parameters_bounds, parameters_init, parameter_objectives) = OcpFes._build_parameters(
            model=input_dict["model"],
            pulse_width=pulse_width,
            pulse_intensity=pulse_intensity,
            use_sx=input_dict["use_sx"],
        )

        numerical_data_time_series, stim_idx_at_node_list = input_dict["model"].get_numerical_data_time_series(
            input_dict["n_shooting"], input_dict["final_time"]
        )

        dynamics = OcpFes._declare_dynamics(input_dict["model"], numerical_data_time_series)
        x_bounds, x_init = OcpFes._set_bounds(input_dict["model"])

        max_bound = (
            pulse_width["max"]
            if isinstance(input_dict["model"], DingModelPulseWidthFrequency)
            else pulse_intensity["max"] if isinstance(input_dict["model"], DingModelPulseIntensityFrequency) else None
        )
        u_bounds, u_init = OcpFes._set_u_bounds(input_dict["model"], max_bound=max_bound)

        objective_functions = OcpFes._set_objective(input_dict["n_shooting"], objective)

        constraints = ConstraintList()
        if isinstance(input_dict["model"], DingModelPulseIntensityFrequency):
            constraints = OcpFes._build_constraints(
                input_dict["model"],
                input_dict["n_shooting"],
                stim_idx_at_node_list,
            )
            OcpFes.update_model_param(input_dict["model"], parameters)

        optimization_dict = {
            "model": input_dict["model"],
            "dynamics": dynamics,
            "n_shooting": input_dict["n_shooting"],
            "final_time": input_dict["final_time"],
            "objective_functions": objective_functions,
            "x_init": x_init,
            "x_bounds": x_bounds,
            "u_bounds": u_bounds,
            "u_init": u_init,
            "constraints": constraints,
            "parameters": parameters,
            "parameters_bounds": parameters_bounds,
            "parameters_init": parameters_init,
            "parameter_objectives": parameter_objectives,
            "use_sx": input_dict["use_sx"],
            "ode_solver": input_dict["ode_solver"],
            "n_threads": input_dict["n_threads"],
            "control_type": input_dict["control_type"],
        }

        return optimization_dict

    @staticmethod
    def prepare_ocp(
        model: FesModel = None,
        final_time: int | float = None,
        pulse_width: dict = None,
        pulse_intensity: dict = None,
        objective: dict = None,
        use_sx: bool = True,
        ode_solver: OdeSolver.RK1 | OdeSolver.RK2 | OdeSolver.RK4 = OdeSolver.RK1(n_integration_steps=10),
        control_type: ControlType = ControlType.CONSTANT,
        n_threads: int = 1,
    ):
        """
        Prepares the Optimal Control Program (OCP) to be solved.

        Parameters
        ----------
        model : FesModel
            The model type used for the OCP.
        final_time : int | float
            The final time of the OCP.
        pulse_width : dict
            Dictionary containing parameters related to the duration of the pulse.
            Optional if not using DingModelPulseWidthFrequency or DingModelPulseWidthFrequencyWithFatigue.
        pulse_intensity : dict
            Dictionary containing parameters related to the intensity of the pulse.
            Optional if not using DingModelPulseIntensityFrequency or DingModelPulseIntensityFrequencyWithFatigue.
        objective : dict
            Dictionary containing parameters related to the optimization objective.
        use_sx : bool
            The nature of the CasADi variables. MX are used if False.
        ode_solver : OdeSolver.RK1 | OdeSolver.RK2 | OdeSolver.RK4
            The ODE solver to use.
        n_threads : int
            The number of threads to use while solving (multi-threading if > 1).
        control_type : ControlType
            The type of control to use.

        Returns
        -------
        OptimalControlProgram
            The prepared Optimal Control Program.
        """

        input_dict = {
            "model": model,
            "n_shooting": OcpFes.prepare_n_shooting(model.stim_time, final_time),
            "final_time": final_time,
            "pulse_width": pulse_width,
            "pulse_intensity": pulse_intensity,
            "objective": objective,
            "use_sx": use_sx,
            "ode_solver": ode_solver,
            "n_threads": n_threads,
            "control_type": control_type,
        }

        optimization_dict = OcpFes._prepare_optimization_problem(input_dict)

        return OptimalControlProgram(
            bio_model=[optimization_dict["model"]],
            dynamics=optimization_dict["dynamics"],
            n_shooting=optimization_dict["n_shooting"],
            phase_time=[optimization_dict["final_time"]],
            objective_functions=optimization_dict["objective_functions"],
            x_init=optimization_dict["x_init"],
            x_bounds=optimization_dict["x_bounds"],
            u_bounds=optimization_dict["u_bounds"],
            u_init=optimization_dict["u_init"],
            constraints=optimization_dict["constraints"],
            parameters=optimization_dict["parameters"],
            parameter_bounds=optimization_dict["parameters_bounds"],
            parameter_init=optimization_dict["parameters_init"],
            parameter_objectives=optimization_dict["parameter_objectives"],
            control_type=optimization_dict["control_type"],
            use_sx=optimization_dict["use_sx"],
            ode_solver=optimization_dict["ode_solver"],
            n_threads=optimization_dict["n_threads"],
        )

    @staticmethod
    def prepare_n_shooting(stim_time, final_time):
        """
        Prepare the n_shooting for the ocp in order to have a time step that is a multiple of the stimulation time.

        Returns
        -------
        int
            The number of shooting points
        """
        # Represent the final time as a Fraction for exact arithmetic.
        T_final = Fraction(final_time).limit_denominator()
        n_shooting = 1

        for t in stim_time:
            # Convert the stimulation time to an exact fraction.
            t_frac = Fraction(t).limit_denominator()
            # Compute the normalized time: t / final_time.
            # This fraction is automatically reduced to the lowest terms.
            norm = t_frac / T_final
            # The denominator in the reduced fraction gives the requirement.
            d = norm.denominator
            n_shooting = n_shooting * d // gcd(n_shooting, d)

        if n_shooting >= 1000:
            print(
                f"Warning: The number of shooting nodes is very high n = {n_shooting}.\n"
                "The optimization might be long, consider using stimulation time with even spacing (common frequency)."
            )

        return n_shooting

    @staticmethod
    def _fill_dict(pulse_width, pulse_intensity, objective):
        """
        This method fills the provided dictionaries with default values if they are not set.

        Parameters
        ----------
        pulse_width : dict
            Dictionary containing parameters related to the duration of the pulse.
            Expected keys are 'fixed', 'min', 'max', and 'bimapping'.

        pulse_intensity : dict
            Dictionary containing parameters related to the intensity of the pulse.
            Expected keys are 'fixed', 'min', 'max', and 'bimapping'.

        objective : dict
            Dictionary containing parameters related to the objective of the optimization.
            Expected keys are 'force_tracking', 'end_node_tracking', and 'custom'.

        Returns
        -------
        Returns four dictionaries: pulse_width, pulse_intensity, and objective.
        Each dictionary is filled with default values for any keys that were not initially set.
        """

        pulse_width = {} if pulse_width is None else pulse_width
        default_pulse_width = {
            "fixed": None,
            "min": None,
            "max": None,
            "bimapping": False,
        }

        pulse_intensity = {} if pulse_intensity is None else pulse_intensity
        default_pulse_intensity = {
            "fixed": None,
            "min": None,
            "max": None,
            "bimapping": False,
        }

        objective = {} if objective is None else objective
        default_objective = {
            "force_tracking": None,
            "end_node_tracking": None,
            "cycling": None,
            "custom": None,
        }

        pulse_width = {**default_pulse_width, **pulse_width}
        pulse_intensity = {**default_pulse_intensity, **pulse_intensity}
        objective = {**default_objective, **objective}

        return pulse_width, pulse_intensity, objective

    @staticmethod
    def _sanity_check(
        model=None,
        n_shooting=None,
        final_time=None,
        objective=None,
        use_sx=None,
        ode_solver=None,
        n_threads=None,
    ):
        if not isinstance(model, FesModel):
            if isinstance(model, FesMskModel):
                pass
            else:
                raise TypeError(
                    f"The current model type used is {type(model)}, it must be a FesModel type."
                    f"Current available models are: DingModelFrequency, DingModelFrequencyWithFatigue,"
                    f"DingModelPulseWidthFrequency, DingModelPulseWidthFrequencyWithFatigue,"
                    f"DingModelPulseIntensityFrequency, DingModelPulseIntensityFrequencyWithFatigue"
                )

        if not isinstance(n_shooting, int) or n_shooting < 0:
            raise TypeError("n_shooting must be a positive int type")

        if not isinstance(final_time, int | float) or final_time < 0:
            raise TypeError("final_time must be a positive int or float type")

        if objective["force_tracking"] is not None:
            if isinstance(objective["force_tracking"], list):
                if isinstance(objective["force_tracking"][0], np.ndarray) and isinstance(
                    objective["force_tracking"][1], np.ndarray
                ):
                    if (
                        len(objective["force_tracking"][0]) != len(objective["force_tracking"][1])
                        or len(objective["force_tracking"]) != 2
                    ):
                        raise ValueError(
                            "force_tracking time and force argument must be same length and force_tracking "
                            "list size 2"
                        )
                else:
                    raise TypeError("force_tracking argument must be np.ndarray type")
            else:
                raise TypeError("force_tracking must be list type")

        if objective["end_node_tracking"] is not None:
            if not isinstance(objective["end_node_tracking"], int | float):
                raise TypeError("end_node_tracking must be int or float type")

        if objective["custom"] is not None:
            if not isinstance(objective["custom"], ObjectiveList):
                raise TypeError("custom_objective must be a ObjectiveList type")
            if not all(isinstance(x, Objective) for x in objective["custom"][0]):
                raise TypeError("All elements in ObjectiveList must be an Objective type")

        if not isinstance(
            ode_solver,
            (OdeSolver.RK1, OdeSolver.RK2, OdeSolver.RK4, OdeSolver.COLLOCATION),
        ):
            raise TypeError("ode_solver must be a OdeSolver type")

        if not isinstance(use_sx, bool):
            raise TypeError("use_sx must be a bool type")

        if not isinstance(n_threads, int):
            raise TypeError("n_thread must be a int type")

    @staticmethod
    def _build_fourier_coefficient(force_tracking):
        return FourierSeries().compute_real_fourier_coeffs(force_tracking[0], force_tracking[1], 50)

    @staticmethod
    def _build_parameters(
        model,
        pulse_intensity,
        use_sx,
        **kwargs,
    ):
        parameters = ParameterList(use_sx=use_sx)
        parameters_bounds = BoundsList()
        parameters_init = InitialGuessList()
        parameter_objectives = ParameterObjectiveList()

        n_stim = len(model.stim_time)

        if isinstance(model, DingModelPulseIntensityFrequency):
            if pulse_intensity["bimapping"]:
                n_stim = 1

            if pulse_intensity["fixed"]:
                parameters.add(
                    name="pulse_intensity",
                    function=DingModelPulseIntensityFrequency.set_impulse_intensity,
                    size=n_stim,
                    scaling=VariableScaling("pulse_intensity", [1] * n_stim),
                )
                if isinstance(pulse_intensity["fixed"], list):
                    parameters_bounds.add(
                        "pulse_intensity",
                        min_bound=np.array(pulse_intensity["fixed"]),
                        max_bound=np.array(pulse_intensity["fixed"]),
                        interpolation=InterpolationType.CONSTANT,
                    )
                    parameters_init.add(
                        key="pulse_intensity",
                        initial_guess=np.array(pulse_intensity["fixed"]),
                    )
                else:
                    parameters_bounds.add(
                        "pulse_intensity",
                        min_bound=np.array([pulse_intensity["fixed"]] * n_stim),
                        max_bound=np.array([pulse_intensity["fixed"]] * n_stim),
                        interpolation=InterpolationType.CONSTANT,
                    )
                    parameters_init["pulse_intensity"] = np.array([pulse_intensity["fixed"]] * n_stim)

            elif pulse_intensity["max"]:
                parameters_bounds.add(
                    "pulse_intensity",
                    min_bound=[model.min_pulse_intensity()],
                    max_bound=[pulse_intensity["max"]],
                    interpolation=InterpolationType.CONSTANT,
                )
                intensity_avg = (model.min_pulse_intensity() + pulse_intensity["max"]) / 2
                parameters_init["pulse_intensity"] = np.array([intensity_avg] * n_stim)
                parameters.add(
                    name="pulse_intensity",
                    function=DingModelPulseIntensityFrequency.set_impulse_intensity,
                    size=n_stim,
                    scaling=VariableScaling("pulse_intensity", [1] * n_stim),
                )

        return (parameters, parameters_bounds, parameters_init, parameter_objectives)

    @staticmethod
    def _build_constraints(model, n_shooting, stim_idx_at_node_list, bimapped_parameters=False, **kwargs):
        constraints = ConstraintList()
        bimapped_parameters_idx_list = [0]
        bimapped_for_nmpc = bimapped_parameters and "n_cycles_simultaneous" in kwargs
        if bimapped_for_nmpc:
            n_repeats = int(n_shooting / kwargs["n_cycles_simultaneous"])
            bimapped_parameters_idx_list = [i for i in range(kwargs["n_cycles_simultaneous"]) for _ in range(n_repeats)]

        if isinstance(model, DingModelPulseIntensityFrequency):
            for i in range(n_shooting):
                # last_stim_idx = stim_idx_at_node_list[i][-1] - model._sum_stim_truncation
                # bimapped_parameters_idx = bimapped_parameters_idx_list[i] if bimapped_for_nmpc else \
                # bimapped_parameters_idx_list[0]

                last_stim_idx = stim_idx_at_node_list[i][-1]

                constraints.add(
                    CustomConstraint.pulse_intensity_sliding_window_constraint,
                    # last_stim_index=last_stim_idx if not bimapped_parameters else bimapped_parameters_idx,
                    last_stim_idx=last_stim_idx,
                    muscle_name=model.muscle_name,
                    node=i,
                )

        return constraints

    @staticmethod
    def _declare_dynamics(model, numerical_data_timeseries=None):
        dynamics = DynamicsList()
        dynamics.add(
            model.declare_ding_variables,
            dynamic_function=model.dynamics,
            expand_dynamics=True,
            phase_dynamics=PhaseDynamics.SHARED_DURING_THE_PHASE,
            numerical_data_timeseries=numerical_data_timeseries,
        )
        return dynamics

    @staticmethod
    def _set_bounds(model):
        # ---- STATE BOUNDS REPRESENTATION ---- #
        #
        #                    |‾‾‾‾‾‾‾‾‾‾x_max_middle‾‾‾‾‾‾‾‾‾‾‾‾x_max_end‾
        #                    |          max_bounds              max_bounds
        #    x_max_start     |
        #   _starting_bounds_|
        #   ‾starting_bounds‾|
        #    x_min_start     |
        #                    |          min_bounds              min_bounds
        #                     ‾‾‾‾‾‾‾‾‾‾x_min_middle‾‾‾‾‾‾‾‾‾‾‾‾x_min_end‾

        # Sets the bound for all the phases
        x_bounds = BoundsList()
        variable_bound_list = model.name_dof
        starting_bounds, min_bounds, max_bounds = (
            model.standard_rest_values(),
            model.standard_rest_values(),
            model.standard_rest_values(),
        )

        for i in range(len(variable_bound_list)):
            if variable_bound_list[i] == "Cn":
                max_bounds[i] = 2
            if variable_bound_list[i] == "F":
                max_bounds[i] = 1000
            elif variable_bound_list[i] == "Tau1" or variable_bound_list[i] == "Km":
                max_bounds[i] = 1
            elif variable_bound_list[i] == "A":
                min_bounds[i] = 0

        starting_bounds_min = np.concatenate((starting_bounds, min_bounds, min_bounds), axis=1)
        starting_bounds_max = np.concatenate((starting_bounds, max_bounds, max_bounds), axis=1)

        for j in range(len(variable_bound_list)):
            x_bounds.add(
                variable_bound_list[j],
                min_bound=np.array([starting_bounds_min[j]]),
                max_bound=np.array([starting_bounds_max[j]]),
                interpolation=InterpolationType.CONSTANT_WITH_FIRST_AND_LAST_DIFFERENT,
            )

        x_init = InitialGuessList()
        for j in range(len(variable_bound_list)):
            x_init.add(variable_bound_list[j], model.standard_rest_values()[j])

        return x_bounds, x_init

    @staticmethod
    def _set_u_bounds(model, max_bound: int | float):
        # Controls bounds
        u_bounds = BoundsList()
        # Controls initial guess
        u_init = InitialGuessList()
        if isinstance(model, DingModelPulseWidthFrequency):
            u_init.add(key="last_pulse_width", initial_guess=[0], phase=0)
            min_pulse_width = model.pd0 if isinstance(model.pd0, int | float) else 0
            u_bounds.add(
                "last_pulse_width",
                min_bound=np.array([[min_pulse_width] * 3]),
                max_bound=np.array([[max_bound] * 3]),
                interpolation=InterpolationType.CONSTANT_WITH_FIRST_AND_LAST_DIFFERENT,
            )

        if isinstance(model, DingModelPulseIntensityFrequency):
            u_init.add(key="pulse_intensity", initial_guess=[0] * model._sum_stim_truncation, phase=0)
            min_pulse_intensity = (
                model.min_pulse_intensity() if isinstance(model.min_pulse_intensity(), int | float) else 0
            )
            u_bounds.add(
                "pulse_intensity",
                min_bound=[min_pulse_intensity] * model._sum_stim_truncation,
                max_bound=[max_bound] * model._sum_stim_truncation,
                interpolation=InterpolationType.CONSTANT,
            )

        return u_bounds, u_init

    @staticmethod
    def _set_objective(n_shooting, objective):
        # Creates the objective for our problem
        objective_functions = ObjectiveList()
        if objective["custom"]:
            for i in range(len(objective["custom"])):
                objective_functions.add(objective["custom"][0][i])

        if objective["force_tracking"]:
            force_fourier_coefficient = (
                None
                if objective["force_tracking"] is None
                else OcpFes._build_fourier_coefficient(objective["force_tracking"])
            )
            force_to_track = FourierSeries().fit_func_by_fourier_series_with_real_coeffs(
                np.linspace(0, 1, n_shooting + 1),
                force_fourier_coefficient,
            )[np.newaxis, :]

            objective_functions.add(
                ObjectiveFcn.Lagrange.TRACK_STATE,
                key="F",
                weight=100,
                target=force_to_track,
                node=Node.ALL,
                quadratic=True,
            )

        if objective["end_node_tracking"]:
            objective_functions.add(
                ObjectiveFcn.Mayer.MINIMIZE_STATE,
                node=Node.END,
                key="F",
                quadratic=True,
                weight=1,
                target=objective["end_node_tracking"],
            )

        return objective_functions

    @staticmethod
    def update_model_param(model, parameters):
        for param_key in parameters:
            if parameters[param_key].function:
                param_scaling = parameters[param_key].scaling.scaling
                param_reduced = parameters[param_key].cx
                parameters[param_key].function(model, param_reduced * param_scaling, **parameters[param_key].kwargs)
