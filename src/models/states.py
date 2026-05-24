from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class MarketState:
    symbol: str
    spot: float
    call_wall: float
    put_wall: float
    gamma_flip: float
    gex: float
    pcr: float
    ifs_score: float
    gamma_regime: str = "ROTATION"
    gex_intensity: float = 0.0

@dataclass
class SetupState:
    symbol: str
    date: str
    setup_type: str
    bias: str
    trigger_strike: float
    invalidation_strike: float
    expected_behavior: str
    dealer_behavior: str

@dataclass
class BreadthState:
    date: str
    bullish_pct: float
    bearish_pct: float
    compression_pct: float
    expansion_pct: float
    transition_pct: float
    mean_rev_pct: float
    total_symbols: int

@dataclass
class PlaybookState:
    bias: str
    trigger_strike: float
    invalidation_strike: float
    expected_behavior: str
    dealer_behavior: str

@dataclass
class SignalState:
    symbol: str
    spot_close: float = 0.0
    spot_change_pct: float = 0.0
    pcr: float = 0.0
    total_ce_oi: float = 0.0
    total_pe_oi: float = 0.0
    delta_ce_oi: float = 0.0
    delta_pe_oi: float = 0.0
    total_volume: float = 0.0
    delta_volume: float = 0.0
    net_inv_shift: float = 0.0
    ifs_score: float = 0.0
    conviction_score: float = 0.0
    priority_score: float = 0.0
    structural_bias: str = "Rotation"
    regime_transition: bool = False
    call_wall: float = 0.0
    put_wall: float = 0.0
    gamma_flip: float = 0.0
    gex: float = 0.0
    gex_intensity: float = 0.0
    gex_shift: float = 0.0
    gamma_regime: str = "ROTATION"
    iv: float = 0.0
    iv_shift: float = 0.0
    bullish_persistence: int = 0
    bearish_persistence: int = 0
    setups: List[str] = field(default_factory=list)
    setups_details: Dict[str, Any] = field(default_factory=dict)
    suggested_strategy: str = "Wait for Setup"

    @classmethod
    def from_dict(cls, symbol: str, d: dict):
        """Creates a SignalState object from a database entry dictionary."""
        return cls(
            symbol=symbol,
            spot_close=float(d.get("spot_close", 0.0)),
            spot_change_pct=float(d.get("spot_change_pct", 0.0)),
            pcr=float(d.get("pcr", 0.0)),
            total_ce_oi=float(d.get("total_ce_oi", 0.0)),
            total_pe_oi=float(d.get("total_pe_oi", 0.0)),
            delta_ce_oi=float(d.get("delta_ce_oi", 0.0)),
            delta_pe_oi=float(d.get("delta_pe_oi", 0.0)),
            total_volume=float(d.get("total_volume", 0.0)),
            delta_volume=float(d.get("delta_volume", 0.0)),
            net_inv_shift=float(d.get("net_inv_shift", 0.0)),
            ifs_score=float(d.get("ifs_score", 0.0)),
            conviction_score=float(d.get("conviction_score", 0.0)),
            priority_score=float(d.get("priority_score", 0.0)),
            structural_bias=str(d.get("structural_bias", "Rotation")),
            regime_transition=bool(d.get("regime_transition", False)),
            call_wall=float(d.get("call_wall", 0.0)),
            put_wall=float(d.get("put_wall", 0.0)),
            gamma_flip=float(d.get("gamma_flip", 0.0)),
            gex=float(d.get("gex", 0.0)),
            gex_intensity=float(d.get("gex_intensity", 0.0)),
            gex_shift=float(d.get("gex_shift", 0.0)),
            gamma_regime=str(d.get("gamma_regime", "ROTATION")),
            iv=float(d.get("iv", 0.0)),
            iv_shift=float(d.get("iv_shift", 0.0)),
            bullish_persistence=int(d.get("bullish_persistence", 0)),
            bearish_persistence=int(d.get("bearish_persistence", 0)),
            setups=list(d.get("setups", [])),
            setups_details=dict(d.get("setups_details", {})),
            suggested_strategy=str(d.get("suggested_strategy", "Wait for Setup"))
        )
