import pandas as pd

from spikecast.data import resolve_group

NEURONS = pd.DataFrame(
    {
        "cell_type": ["DNa02", "DNa02", "DM1_lPN", "DA1_lPN", "PPL101", None],
        "cell_class": [None, None, "ALPN", "ALPN", "DAN", "ALPN"],
        "cell_sub_class": [None, None, "uniglomerular", "uniglomerular", None, "multiglomerular"],
        "side": ["left", "right", "left", "left", "right", "left"],
    }
)


def indices(select):
    return NEURONS.index[resolve_group(NEURONS, {"select": select})].tolist()


def test_single_value_filter():
    assert indices({"cell_type": "DNa02"}) == [0, 1]


def test_filters_are_anded():
    assert indices({"cell_type": "DNa02", "side": "right"}) == [1]


def test_list_value_matches_any_member():
    assert indices({"cell_sub_class": ["uniglomerular", "multiglomerular"]}) == [2, 3, 5]


def test_regex_must_match_the_whole_cell_type_and_skips_untyped_neurons():
    assert indices({"cell_class": "ALPN", "cell_type_regex": "(DM1|DM2)_.*PN"}) == [2]
    assert indices({"cell_type_regex": "PPL1"}) == []  # partial match is not enough
    assert indices({"cell_type_regex": "PPL1\\d+"}) == [4]
