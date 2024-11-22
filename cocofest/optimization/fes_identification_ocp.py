import numpy as np

from bioptim import (
    BoundsList,
    ConstraintList,
    ControlType,
    InitialGuessList,
    InterpolationType,
    Objective,
    ObjectiveFcn,
    ObjectiveList,
    OdeSolver,
    OptimalControlProgram,
    ParameterList,
    PhaseTransitionFcn,
    PhaseTransitionList,
    VariableScaling,
    Node,
)

from ..models.fes_model import FesModel

from ..models.ding2003 import DingModelFrequency
from ..models.ding2007 import DingModelPulseWidthFrequency
from ..models.hmed2018 import DingModelPulseIntensityFrequency
from ..optimization.fes_ocp import OcpFes
from ..custom_constraints import CustomConstraint


class OcpFesId(OcpFes):
    def __init__(self):
        super(OcpFesId, self).__init__()

    @staticmethod
    def prepare_ocp(
        model: FesModel = None,
        final_time: float | int = None,
        stim_time: list = None,
        pulse_width: dict = None,
        pulse_intensity: dict = None,
        objective: dict = None,
        key_parameter_to_identify: list = None,
        additional_key_settings: dict = None,
        custom_objective: list[Objective] = None,
        discontinuity_in_ocp: list = None,
        use_sx: bool = True,
        ode_solver: OdeSolver = OdeSolver.RK4(n_integration_steps=1),
        n_threads: int = 1,
        control_type: ControlType = ControlType.CONSTANT,
        **kwargs,
    ):
        """
        The main class to define an ocp. This class prepares the full program and gives all
        the needed parameters to solve a functional electrical stimulation ocp

        Attributes
        ----------
        model:  FesModel
            The model used to solve the ocp
        final_time: float, int
            The final time of each phase, it corresponds to the stimulation apparition time
        pulse_width: dict,
            The duration of the stimulation
        pulse_intensity: dict,
            The intensity of the stimulation
        objective: dict,
            The objective to minimize
        discontinuity_in_ocp: list[int],
            The phases where the continuity is not respected
        ode_solver: OdeSolver
            The ode solver to use
        use_sx: bool
            The nature of the casadi variables. MX are used if False.
        n_thread: int
            The number of thread to use while solving (multi-threading if > 1)
        """
        (
            pulse_event,
            pulse_width,
            pulse_intensity,
            temp_objective,
        ) = OcpFes._fill_dict({}, pulse_width, pulse_intensity, {})

        n_shooting = OcpFes.prepare_n_shooting(stim_time, final_time)
        OcpFesId._sanity_check(
            model=model,
            n_shooting=n_shooting,
            final_time=final_time,
            pulse_event=pulse_event,
            pulse_width=pulse_width,
            pulse_intensity=pulse_intensity,
            objective=temp_objective,
            use_sx=use_sx,
            ode_solver=ode_solver,
            n_threads=n_threads,
        )

        OcpFesId._sanity_check_id(
            model=model,
            final_time=final_time,
            objective=objective,
            pulse_width=pulse_width,
            pulse_intensity=pulse_intensity,
        )

        n_stim = len(stim_time)

        parameters, parameters_bounds, parameters_init = OcpFesId._set_parameters(
            n_stim=n_stim,
            stim_apparition_time=stim_time,
            parameter_to_identify=key_parameter_to_identify,
            parameter_setting=additional_key_settings,
            pulse_width=pulse_width,
            pulse_intensity=pulse_intensity,
            use_sx=use_sx,
        )

        OcpFesId.update_model_param(model, parameters)

        dynamics = OcpFesId._declare_dynamics(model=model)
        x_bounds, x_init = OcpFesId._set_bounds(
            model=model,
            force_tracking=objective["force_tracking"],
            discontinuity_in_ocp=discontinuity_in_ocp,
        )
        objective_functions = OcpFesId._set_objective(model=model, objective=objective)

        if model.is_approximated:
            constraints = OcpFesId._build_constraints(
                model=model,
                n_shooting=n_shooting,
                final_time=final_time,
                stim_time=stim_time,
                control_type=control_type,
            )
            u_bounds, u_init = OcpFesId._set_u_bounds(model=model)
        else:
            constraints = ConstraintList()
            u_bounds, u_init = None, None

        # phase_transitions = OcpFesId._set_phase_transition(discontinuity_in_ocp)

        return OptimalControlProgram(
            bio_model=[model],
            dynamics=dynamics,
            n_shooting=n_shooting,
            phase_time=final_time,
            x_init=x_init,
            x_bounds=x_bounds,
            u_init=u_init,
            u_bounds=u_bounds,
            objective_functions=objective_functions,
            constraints=constraints,
            ode_solver=ode_solver,
            control_type=control_type,
            use_sx=use_sx,
            parameters=parameters,
            parameter_bounds=parameters_bounds,
            parameter_init=parameters_init,
            # phase_transitions=phase_transitions,
            n_threads=n_threads,
        )

    @staticmethod
    def _sanity_check_id(
        model=None,
        final_time=None,
        objective=None,
        pulse_width=None,
        pulse_intensity=None,
    ):
        if not isinstance(final_time, int | float):
            raise TypeError(f"final_time must be int or float type.")

        if not isinstance(objective["force_tracking"], list):
            raise TypeError(
                f"force_tracking must be list type,"
                f" currently force_tracking is {type(objective['force_tracking'])}) type."
            )
        else:
            if not all(isinstance(val, int | float) for val in objective["force_tracking"]):
                raise TypeError(f"force_tracking must be list of int or float type.")

        if isinstance(model, DingModelPulseWidthFrequency):
            if not isinstance(pulse_width, dict):
                raise TypeError(
                    f"pulse_width must be dict type," f" currently pulse_width is {type(pulse_width)}) type."
                )

        if isinstance(model, DingModelPulseIntensityFrequency):
            if isinstance(pulse_intensity, dict):
                if not isinstance(pulse_intensity["fixed"], int | float | list):
                    raise ValueError(f"fixed pulse_intensity must be a int, float or list type.")

            else:
                raise TypeError(
                    f"pulse_intensity must be dict type,"
                    f" currently pulse_intensity is {type(pulse_intensity)}) type."
                )

    @staticmethod
    def _set_bounds(
        model: FesModel = None,
        force_tracking=None,
        discontinuity_in_ocp=None,
    ):
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
                max_bounds[i] = 10
            elif variable_bound_list[i] == "F":
                max_bounds[i] = 500
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
                phase=0,
                interpolation=InterpolationType.CONSTANT_WITH_FIRST_AND_LAST_DIFFERENT,
            )

        x_init = InitialGuessList()

        x_init.add(
            "F",
            np.array([force_tracking]),
            phase=0,
            interpolation=InterpolationType.EACH_FRAME,
        )
        x_init.add("Cn", [0], phase=0, interpolation=InterpolationType.CONSTANT)
        if model._with_fatigue:
            for j in range(len(variable_bound_list)):
                if variable_bound_list[j] == "F" or variable_bound_list[j] == "Cn":
                    pass
                else:
                    x_init.add(variable_bound_list[j], model.standard_rest_values()[j])

        return x_bounds, x_init

    @staticmethod
    def _set_objective(model, objective):
        # Creates the objective for our problem (in this case, match a force curve)
        objective_functions = ObjectiveList()

        if objective["force_tracking"]:
            objective_functions.add(
                ObjectiveFcn.Lagrange.TRACK_STATE,
                key="F",
                weight=1,
                target=np.array(objective["force_tracking"])[np.newaxis, :],
                node=Node.ALL,
                quadratic=True,
            )

        if "custom" in objective and objective["custom"] is not None:
            for i in range(len(objective["custom"])):
                objective_functions.add(objective["custom"][i])

        return objective_functions

    @staticmethod
    def _set_parameters(
        n_stim,
        stim_apparition_time,
        parameter_to_identify,
        parameter_setting,
        use_sx,
        pulse_width: dict = None,
        pulse_intensity: dict = None,
    ):
        parameters = ParameterList(use_sx=use_sx)
        parameters_bounds = BoundsList()
        parameters_init = InitialGuessList()

        parameters.add(
            name="pulse_apparition_time",
            function=DingModelFrequency.set_pulse_apparition_time,
            size=n_stim,
            scaling=VariableScaling("pulse_apparition_time", [1] * n_stim),
        )

        parameters_init["pulse_apparition_time"] = np.array(stim_apparition_time)

        parameters_bounds.add(
            "pulse_apparition_time",
            min_bound=stim_apparition_time,
            max_bound=stim_apparition_time,
            interpolation=InterpolationType.CONSTANT,
        )

        for i in range(len(parameter_to_identify)):
            parameters.add(
                name=parameter_to_identify[i],
                function=parameter_setting[parameter_to_identify[i]]["function"],
                size=1,
                scaling=VariableScaling(
                    parameter_to_identify[i],
                    [parameter_setting[parameter_to_identify[i]]["scaling"]],
                ),
            )
            parameters_bounds.add(
                parameter_to_identify[i],
                min_bound=np.array([parameter_setting[parameter_to_identify[i]]["min_bound"]]),
                max_bound=np.array([parameter_setting[parameter_to_identify[i]]["max_bound"]]),
                interpolation=InterpolationType.CONSTANT,
            )
            parameters_init.add(
                key=parameter_to_identify[i],
                initial_guess=np.array([parameter_setting[parameter_to_identify[i]]["initial_guess"]]),
            )

        if pulse_width["fixed"]:
            parameters.add(
                name="pulse_width",
                function=DingModelPulseWidthFrequency.set_impulse_width,
                size=n_stim,
                scaling=VariableScaling("pulse_width", [1] * n_stim),
            )
            if isinstance(pulse_width["fixed"], list):
                parameters_bounds.add(
                    "pulse_width",
                    min_bound=np.array(pulse_width["fixed"]),
                    max_bound=np.array(pulse_width["fixed"]),
                    interpolation=InterpolationType.CONSTANT,
                )
                parameters_init.add(key="pulse_width", initial_guess=np.array(pulse_width["fixed"]))
            else:
                parameters_bounds.add(
                    "pulse_width",
                    min_bound=np.array([pulse_width["fixed"]] * n_stim),
                    max_bound=np.array([pulse_width["fixed"]] * n_stim),
                    interpolation=InterpolationType.CONSTANT,
                )
                parameters_init.add(
                    key="pulse_width",
                    initial_guess=np.array([pulse_width] * n_stim),
                )

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
                parameters_init.add(key="pulse_intensity", initial_guess=np.array(pulse_intensity["fixed"]))
            else:
                parameters_bounds.add(
                    "pulse_intensity",
                    min_bound=np.array([pulse_intensity["fixed"]] * n_stim),
                    max_bound=np.array([pulse_intensity["fixed"]] * n_stim),
                    interpolation=InterpolationType.CONSTANT,
                )
                parameters_init.add(
                    key="pulse_intensity",
                    initial_guess=np.array([pulse_intensity["fixed"]] * n_stim),
                )

        return parameters, parameters_bounds, parameters_init

    @staticmethod
    def _build_constraints(model, n_shooting, final_time, stim_time, control_type):
        constraints = ConstraintList()

        time_vector = np.linspace(0, final_time, n_shooting + 1)
        stim_at_node = [np.where(stim_time[i] <= time_vector)[0][0] for i in range(len(stim_time))]
        additional_nodes = 1 if control_type == ControlType.LINEAR_CONTINUOUS else 0
        if model._sum_stim_truncation:
            max_stim_to_keep = model._sum_stim_truncation
        else:
            max_stim_to_keep = 10000000

        index_sup = 0
        index_inf = 0
        stim_index = []
        for i in range(n_shooting + additional_nodes):
            if i in stim_at_node:
                index_sup += 1
                if index_sup >= max_stim_to_keep:
                    index_inf = index_sup - max_stim_to_keep
                stim_index = [i for i in range(index_inf, index_sup)]

            constraints.add(
                CustomConstraint.cn_sum_identification,
                node=i,
                stim_time=stim_time[index_inf:index_sup],
                stim_index=stim_index,
            )

        if isinstance(model, DingModelPulseWidthFrequency):
            index_sup = 0
            for i in range(n_shooting + additional_nodes):
                if i in stim_at_node and i != 0:
                    index_sup += 1
                constraints.add(
                    CustomConstraint.a_calculation_identification,
                    node=i,
                    last_stim_index=index_sup,
                )

        return constraints

    @staticmethod
    def _set_phase_transition(discontinuity_in_ocp):
        phase_transitions = PhaseTransitionList()
        if discontinuity_in_ocp:
            for i in range(len(discontinuity_in_ocp)):
                phase_transitions.add(
                    PhaseTransitionFcn.DISCONTINUOUS,
                    phase_pre_idx=discontinuity_in_ocp[i] - 1,
                )
        return phase_transitions
