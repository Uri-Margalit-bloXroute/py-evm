import functools
import itertools

from cytoolz import (
    cons,
    sliding_window,
    take,
)
from eth_utils import (
    to_tuple,
)

from cancel_token import CancelToken

from p2p import protocol
from p2p.peer import BasePeer
from p2p.protocol import Command

from eth.exceptions import BlockNotFound
from eth.beacon.db.chain import BaseBeaconChainDB
from eth.beacon.types.blocks import BaseBeaconBlock

from trinity.protocol.common.servers import BaseRequestServer
from trinity.protocol.bcc import commands
from trinity.protocol.bcc.peer import (
    BCCPeer,
    BCCPeerPool,
)

from typing import (
    cast,
    Any,
    Dict,
    Iterable,
    Set,
    Type,
)
from eth_typing import (
    Hash32,
)


class BCCRequestServer(BaseRequestServer):
    subscription_msg_types: Set[Type[Command]] = {
        commands.GetBeaconBlocks,
    }

    def __init__(self,
                 db: BaseBeaconChainDB,
                 peer_pool: BCCPeerPool,
                 token: CancelToken = None) -> None:
        super().__init__(peer_pool, token)
        self.db = db

    async def _handle_msg(self, base_peer: BasePeer, cmd: Command,
                          msg: protocol._DecodedMsgType) -> None:
        peer = cast(BCCPeer, base_peer)

        if isinstance(cmd, commands.GetBeaconBlocks):
            await self._handle_get_beacon_blocks(peer, cast(Dict[str, Any], msg))
        else:
            raise Exception("Invariant: Only subscribed to GetBeaconBlocks")

    async def _handle_get_beacon_blocks(self, peer: BCCPeer, msg: Dict[str, Any]) -> None:
        if not peer.is_operational:
            return

        max_blocks = cast(int, msg["max_blocks"])
        block_slot_or_hash = msg["block_slot_or_hash"]

        if isinstance(block_slot_or_hash, int):
            get_start_block = functools.partial(
                self.db.get_canonical_block_by_slot,
                cast(int, block_slot_or_hash),
            )
        elif isinstance(block_slot_or_hash, bytes):
            get_start_block = functools.partial(
                self.db.get_block_by_hash,
                cast(Hash32, block_slot_or_hash),
            )
        else:
            actual_type = type(block_slot_or_hash)
            raise TypeError(f"Invariant: unexpected type for 'block_slot_or_hash': {actual_type}")

        try:
            start_block = get_start_block()
        except BlockNotFound:
            self.logger.debug2("%s requested unknown block %s", block_slot_or_hash)
            blocks = ()
        else:
            self.logger.debug2(
                "%s requested %d blocks starting with %s",
                peer,
                max_blocks,
                start_block,
            )
            blocks = self._get_blocks(start_block, max_blocks)
        finally:
            self.logger.debug2("Replying to %s with %d blocks", peer, len(blocks))
            peer.sub_proto.send_blocks(blocks)

    @to_tuple
    def _get_blocks(self,
                    start_block: BaseBeaconBlock,
                    max_blocks: int) -> Iterable[BaseBeaconBlock]:
        if max_blocks <= 0:
            return

        yield start_block

        blocks_generator = cons(start_block, (
            self.db.get_canonical_block_by_slot(slot)
            for slot in itertools.count(start_block.slot + 1)
        ))
        max_blocks_generator = take(max_blocks, blocks_generator)

        try:
            # ensure only a connected chain is returned (breaks might occur if the start block is
            # not part of the canonical chain or if the canonical chain changes during execution)
            for parent, child in sliding_window(2, max_blocks_generator):
                if child.parent_hash == parent.hash:
                    yield child
                else:
                    break
        except BlockNotFound:
            return
