import numpy as np

from bioptim import (
    BoundsList,
    ConstraintList,
    ControlType,
    DynamicsList,
    InitialGuessList,
    InterpolationType,
    Objective,
    ObjectiveFcn,
    ObjectiveList,
    OdeSolver,
    OptimalControlProgram,
    ParameterList,
    ParameterObjectiveList,
)
from ding_model_identification import ForceDingModelFrequencyIdentification, FatigueDingModelFrequencyIdentification
from optistim.custom_objectives import CustomObjective
from optistim.fourier_approx import FourierSeries
from fext_to_fmuscle import ForceSensorToMuscleForce


class FunctionalElectricStimulationOptimalControlProgramIdentification(OptimalControlProgram):
    """
    The main class to define an ocp. This class prepares the full program and gives all
    the needed parameters to solve a functional electrical stimulation ocp

    Attributes
    ----------
    ding_model: ForceDingModelFrequencyIdentification | FatigueDingModelFrequencyIdentification
        The model type used for the ocp
    n_shooting: int
        Number of shooting point for each individual phases
    force_tracking: list[np.ndarray, np.ndarray]
        List of time and associated force to track during ocp optimisation
    pulse_apparition_time: list[int] | list[float]
        Setting a chosen pulse apparition time among ocp
    pulse_duration: list[int] | list[float]
        Setting a chosen pulse time among phases
    pulse_intensity: list[int] | list[float]
        Setting a chosen pulse intensity among phases
    **kwargs:
        objective: list[Objective]
            Additional objective for the system
        ode_solver: OdeSolver
            The ode solver to use
        use_sx: bool
            The nature of the casadi variables. MX are used if False.
        n_threads: int
            The number of thread to use while solving (multi-threading if > 1)

    # Methods
    # -------
    # from_frequency_and_final_time(self, frequency: int | float, final_time: float, round_down: bool)
    #     Calculates the number of stim (phases) for the ocp from frequency and final time
    # from_frequency_and_n_stim(self, frequency: int | float, n_stim: int)
    #     Calculates the final ocp time from frequency and stimulation number
    """

    def __init__(
        self,
        ding_model: ForceDingModelFrequencyIdentification | FatigueDingModelFrequencyIdentification,
        n_shooting: int = None,
        force_tracking: list[np.ndarray, np.ndarray] = None,
        pulse_apparition_time: list[int] | list[float] = None,
        pulse_duration: list[int] | list[float] = None,
        pulse_intensity: list[int] | list[float] = None,
        a_rest: float = None,
        km_rest: float = None,
        tau1_rest: float = None,
        tau2: float = None,
        **kwargs,
    ):
        if isinstance(ding_model, FatigueDingModelFrequencyIdentification):
            if any(elem is None for elem in [a_rest, km_rest, tau1_rest, tau2]):
                raise ValueError("a_rest, km_rest, tau1_rest and tau2 must be set for fatigue model identification")
            ding_model.set_a_rest(a_rest)
            ding_model.set_km_rest(km_rest)
            ding_model.set_tau1_rest(tau1_rest)
            ding_model.set_tau2(tau2)

        self.ding_model = ding_model
        self.force_tracking = force_tracking

        if force_tracking is not None:
            force_fourier_coef = FourierSeries()
            if isinstance(force_tracking, list):
                if isinstance(force_tracking[0], np.ndarray) and isinstance(force_tracking[1], np.ndarray):
                    if len(force_tracking[0]) == len(force_tracking[1]) and len(force_tracking) == 2:
                        force_fourier_coef = force_fourier_coef.compute_real_fourier_coeffs(
                            force_tracking[0], force_tracking[1], 50
                        )
                    else:
                        raise ValueError(
                            "force_tracking time and force argument must be same length and force_tracking "
                            "list size 2"
                        )
                else:
                    raise ValueError("force_tracking argument must be np.ndarray type")
            else:
                raise ValueError("force_tracking must be list type")
            self.force_fourier_coef = force_fourier_coef
        else:
            self.force_fourier_coef = None

        self.parameter_mappings = None
        self.parameters = None

        pulse_apparition_time = [item for sublist in pulse_apparition_time for item in sublist]
        if not isinstance(pulse_apparition_time, list):
            raise TypeError(f"pulse_apparition_time must be list type,"
                            f" currently pulse_apparition_time is {type(pulse_apparition_time)}) type.")

        self.ding_models = [ding_model] * len(pulse_apparition_time)
        # TODO : when other model are implemented, add veriification on len pulse_apparition_time and pulse_duration and pulse_intensity
        self.n_shooting = [n_shooting] * (len(pulse_apparition_time)-1)
        self.n_shooting.append(n_shooting*len(pulse_apparition_time))
        constraints = ConstraintList()
        for i in range(len(pulse_apparition_time)):
            self.final_time_phase = (pulse_apparition_time[i + 1],) if i == 0 else self.final_time_phase + (
            pulse_apparition_time[i] - pulse_apparition_time[i - 1],) if i != len(pulse_apparition_time) - 1 else self.final_time_phase + (
            1,)

        self.n_stim = len(self.final_time_phase)

        if isinstance(ding_model, ForceDingModelFrequencyIdentification):
            self.parameters, self.parameters_bounds, self.parameters_init, self.parameter_objectives = self.force()
        # if isinstance(ding_model, ForceDingModelFrequencyIdentification):
        #     self.parameters, self.parameters_bounds, self.parameters_init, self.parameter_objectives = self.fatigue()

        self._declare_dynamics()
        self._set_bounds()
        self.kwargs = kwargs
        self._set_objective()

        if "ode_solver" in kwargs:
            if not isinstance(kwargs["ode_solver"], OdeSolver):
                raise ValueError("ode_solver kwarg must be a OdeSolver type")

        if "use_sx" in kwargs:
            if not isinstance(kwargs["use_sx"], bool):
                raise ValueError("use_sx kwarg must be a bool type")

        if "n_thread" in kwargs:
            if not isinstance(kwargs["n_thread"], int):
                raise ValueError("n_thread kwarg must be a int type")

        super().__init__(
            bio_model=self.ding_models,
            dynamics=self.dynamics,
            n_shooting=self.n_shooting,
            phase_time=self.final_time_phase,
            x_init=self.x_init,
            u_init=self.u_init,
            x_bounds=self.x_bounds,
            u_bounds=self.u_bounds,
            objective_functions=self.objective_functions,
            constraints=constraints,
            ode_solver=kwargs["ode_solver"] if "ode_solver" in kwargs else OdeSolver.RK4(n_integration_steps=1),
            control_type=ControlType.NONE,
            use_sx=kwargs["use_sx"] if "use_sx" in kwargs else False,
            parameters=self.parameters,
            parameter_bounds=self.parameters_bounds,
            parameter_init=self.parameters_init,
            parameter_objectives=self.parameter_objectives,
            assume_phase_dynamics=False,
            n_threads=kwargs["n_thread"] if "n_thread" in kwargs else 1,
            # skip_continuity=False
        )

    def _declare_dynamics(self):
        self.dynamics = DynamicsList()
        for i in range(self.n_stim):
            self.dynamics.add(
                self.ding_models[i].declare_ding_variables,
                dynamic_function=self.ding_models[i].dynamics,
                phase=i,
            )

    def _set_bounds(self):
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
        self.x_bounds = BoundsList()
        variable_bound_list = self.ding_model.name_dof
        starting_bounds, min_bounds, max_bounds = (
            self.ding_model.standard_rest_values(),
            self.ding_model.standard_rest_values(),
            self.ding_model.standard_rest_values(),
        )

        for i in range(len(variable_bound_list)):
            if variable_bound_list[i] == "Cn" or variable_bound_list[i] == "F":
                max_bounds[i] = 1000
            elif variable_bound_list[i] == "Tau1" or variable_bound_list[i] == "Km":
                max_bounds[i] = 1
            elif variable_bound_list[i] == "A":
                min_bounds[i] = 0

        starting_bounds_min = np.concatenate((starting_bounds, min_bounds, min_bounds), axis=1)
        starting_bounds_max = np.concatenate((starting_bounds, max_bounds, max_bounds), axis=1)
        middle_bound_min = np.concatenate((min_bounds, min_bounds, min_bounds), axis=1)
        middle_bound_max = np.concatenate((max_bounds, max_bounds, max_bounds), axis=1)

        for i in range(self.n_stim):
            for j in range(len(variable_bound_list)):
                if i == 0:
                    self.x_bounds.add(
                        variable_bound_list[j],
                        min_bound=np.array([starting_bounds_min[j]]),
                        max_bound=np.array([starting_bounds_max[j]]),
                        phase=i,
                        interpolation=InterpolationType.CONSTANT_WITH_FIRST_AND_LAST_DIFFERENT,
                    )
                else:
                    self.x_bounds.add(
                        variable_bound_list[j],
                        min_bound=np.array([middle_bound_min[j]]),
                        max_bound=np.array([middle_bound_max[j]]),
                        phase=i,
                        interpolation=InterpolationType.CONSTANT_WITH_FIRST_AND_LAST_DIFFERENT,
                    )

        self.x_init = InitialGuessList()
        for i in range(self.n_stim):
            force_in_phase = self.input_force(self.force_tracking[0], self.force_tracking[1], i)
            self.x_init.add("F", np.array([force_in_phase]), phase=i, interpolation=InterpolationType.EACH_FRAME)
            self.x_init.add("Cn", [0], phase=i, interpolation=InterpolationType.CONSTANT)

        # Creates the controls of our problem (in our case, equals to an empty list)
        self.u_bounds = BoundsList()
        for i in range(self.n_stim):
            self.u_bounds.add("", min_bound=[], max_bound=[])

        self.u_init = InitialGuessList()
        for i in range(self.n_stim):
            self.u_init.add("", min_bound=[], max_bound=[])

    def input_force(self, time, force, phase_idx):
        current_time = sum(self.final_time_phase[:phase_idx])
        # current_time_end = current_time + self.final_time_phase[phase_idx]
        dt = self.final_time_phase[phase_idx] / (self.n_shooting[phase_idx]+1)
        force_idx = []
        for i in range(self.n_shooting[phase_idx]+1):
            force_idx.append(np.where(time == round(current_time, 3))[0][0])
            current_time += dt
        force_in_phase = [force[i] for i in force_idx]
        return force_in_phase

        # TODO : add input force
        pass

    def _set_objective(self):
        # Creates the objective for our problem (in this case, match a force curve)
        self.objective_functions = ObjectiveList()
        if "objective" in self.kwargs:
            if self.kwargs["objective"] is not None:
                if not isinstance(self.kwargs["objective"], list):
                    raise ValueError("objective kwarg must be a list type")
                if all(isinstance(x, Objective) for x in self.kwargs["objective"]):
                    for i in range(len(self.kwargs["objective"])):
                        self.objective_functions.add(self.kwargs["objective"][i])
                else:
                    raise ValueError("All elements in objective kwarg must be an Objective type")

        if self.force_fourier_coef is not None:
            for phase in range(self.n_stim):
                for i in range(self.n_shooting[phase]):
                    self.objective_functions.add(
                        CustomObjective.track_state_from_time,
                        custom_type=ObjectiveFcn.Mayer,
                        node=i,
                        fourier_coeff=self.force_fourier_coef,
                        key="F",
                        quadratic=True,
                        weight=1,
                        phase=phase,
                    )

    def force(self):
        parameters = ParameterList()
        parameters_bounds = BoundsList()
        parameters_init = InitialGuessList()
        parameter_objectives = ParameterObjectiveList()

        if isinstance(self.ding_model, ForceDingModelFrequencyIdentification):
            # --- Adding parameters --- #
            parameters.add(
                parameter_name="a_rest",
                list_index=0,
                function=ForceDingModelFrequencyIdentification.set_a_rest,
                size=1,
            )
            parameters.add(
                parameter_name="km_rest",
                list_index=1,
                function=ForceDingModelFrequencyIdentification.set_km_rest,
                size=1,
            )
            parameters.add(
                parameter_name="tau1_rest",
                list_index=2,
                function=ForceDingModelFrequencyIdentification.set_tau1_rest,
                size=1,
            )
            parameters.add(
                parameter_name="tau2",
                list_index=3,
                function=ForceDingModelFrequencyIdentification.set_tau2,
                size=1,
            )

            # --- Adding bound parameters --- #
            parameters_bounds.add(
                "a_rest",
                min_bound=np.array([0]),  # TODO : set bounds
                max_bound=np.array([10000]),
                interpolation=InterpolationType.CONSTANT,
            )
            parameters_bounds.add(
                "km_rest",
                min_bound=np.array([0.01]),  # TODO : set bounds
                max_bound=np.array([1]),
                interpolation=InterpolationType.CONSTANT,
            )
            parameters_bounds.add(
                "tau1_rest",
                min_bound=np.array([0.01]),  # TODO : set bounds
                max_bound=np.array([1]),
                interpolation=InterpolationType.CONSTANT,
            )
            parameters_bounds.add(
                "tau2",
                min_bound=np.array([0.01]),  # TODO : set bounds
                max_bound=np.array([1]),
                interpolation=InterpolationType.CONSTANT,
            )

            # --- Initial guess parameters --- #
            parameters_init["a_rest"] = np.array([1000])  # TODO : set initial guess
            parameters_init["km_rest"] = np.array([0.5])  # TODO : set initial guess
            parameters_init["tau1_rest"] = np.array([0.5])  # TODO : set initial guess
            parameters_init["tau2"] = np.array([0.5])  # TODO : set initial guess

            return parameters, parameters_bounds, parameters_init, parameter_objectives

    def fatigue(self):
        parameters = ParameterList()
        parameters_bounds = BoundsList()
        parameters_init = InitialGuessList()
        parameter_objectives = ParameterObjectiveList()

        if isinstance(self.ding_model, FatigueDingModelFrequencyIdentification):
            # --- Adding parameters --- #
            parameters.add(
                parameter_name="alpha_a",
                list_index=0,
                function=FatigueDingModelFrequencyIdentification.set_alpha_a,
                size=1,
            )
            parameters.add(
                parameter_name="alpha_km",
                list_index=1,
                function=FatigueDingModelFrequencyIdentification.set_alpha_km,
                size=1,
            )
            parameters.add(
                parameter_name="alpha_tau1",
                list_index=2,
                function=FatigueDingModelFrequencyIdentification.set_alpha_tau1,
                size=1,
            )
            parameters.add(
                parameter_name="tau_fat",
                list_index=3,
                function=FatigueDingModelFrequencyIdentification.set_tau_fat,
                size=1,
            )

            # --- Adding bound parameters --- #
            parameters_bounds.add(
                "a_rest",
                min_bound=np.array([0]),  # TODO : set bounds
                max_bound=np.array([10000]),
                interpolation=InterpolationType.CONSTANT,
            )
            parameters_bounds.add(
                "km_rest",
                min_bound=np.array([0]),  # TODO : set bounds
                max_bound=np.array([1]),
                interpolation=InterpolationType.CONSTANT,
            )
            parameters_bounds.add(
                "tau1_rest",
                min_bound=np.array([0]),  # TODO : set bounds
                max_bound=np.array([1]),
                interpolation=InterpolationType.CONSTANT,
            )
            parameters_bounds.add(
                "tau2",
                min_bound=np.array([0]),  # TODO : set bounds
                max_bound=np.array([1]),
                interpolation=InterpolationType.CONSTANT,
            )

            # --- Initial guess parameters --- #
            parameters_init["a_rest"] = np.array([1000])  # TODO : set initial guess
            parameters_init["km_rest"] = np.array([0.1])  # TODO : set initial guess
            parameters_init["tau1_rest"] = np.array([0.01])  # TODO : set initial guess
            parameters_init["tau2"] = np.array([0.01])  # TODO : set initial guess

            return parameters, parameters_bounds, parameters_init, parameter_objectives


if __name__ == "__main__":

    biceps_force = ForceSensorToMuscleForce(path="D:/These/Programmation/Ergometer_pedal_force/Excel_test.xlsx")
    biceps_force = biceps_force.biceps_force_vector


