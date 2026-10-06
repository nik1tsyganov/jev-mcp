"""One place that binds frozen catalogs, product authority and the callable for a run."""
from .authority import product_snapshot, seat_pin, seed
from .common import FROZEN_INPUTS
from .frozen import verify_snapshot
from .helper import Helper, helper_input, materialize
from .native_guard import NativeGuard


class Context:
    def __init__(self, cases, frozen=FROZEN_INPUTS, seed_authority=True, app=None):
        self.catalogs = verify_snapshot(frozen)
        self.guard = NativeGuard(frozen)
        self.snapshot = product_snapshot(frozen)
        self.seats = seat_pin(frozen)
        self.matrix_version = self.seats["matrixVersion"]
        self.authority = seed(cases, self.guard, frozen) if seed_authority else {}
        self.helper = Helper(self.authority, app=app) if seed_authority else None
        for case in cases:
            case["_native"] = materialize(case, self.snapshot)

    def input(self, case, backend, model, threshold, evidence):
        return helper_input(case, backend, model, threshold, self.guard, evidence, self.matrix_version, self.snapshot)
