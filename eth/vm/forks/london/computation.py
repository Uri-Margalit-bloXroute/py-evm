from eth.exceptions import ReservedBytesInCode
from eth.vm.forks.berlin.computation import (
    BerlinComputation,
)

from .opcodes import LONDON_OPCODES
from ..london.constants import EIP3541_RESERVED_STARTING_BYTE


class LondonComputation(BerlinComputation):
    """
    A class for all execution computations in the ``London`` fork.
    Inherits from :class:`~eth.vm.forks.berlin.BerlinComputation`
    """
    opcodes = LONDON_OPCODES

    @classmethod
    def validate_new_contract_code(cls, contract_code: bytes) -> None:
        if contract_code[:1] == EIP3541_RESERVED_STARTING_BYTE:
            raise ReservedBytesInCode(
                "Contract code begins with EIP3541 reserved byte '0xEF'."
            )
