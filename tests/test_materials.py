"""Material catalog, data-availability flags, and role-based template builds (data-free)."""

from nbeast.core import materials, specs, templates

# The nuclides + thermal tables NBEAST's curated offline bundle carries.
BUNDLE = {
    "H1", "H2", "O16", "O17", "O18", "U234", "U235", "U236", "U238",
    "Zr90", "Zr91", "Zr92", "Zr94", "Zr96", "c_H_in_H2O",
}


def test_plutonium_metal_is_a_fuel_needing_only_pu():
    spec = materials.LIBRARY["plutonium_metal"]
    assert "fuel" in spec.categories             # selectable in Godiva's fuel dropdown
    assert set(spec.build().get_nuclides()) == {"Pu239", "Pu240"}
    assert spec.required_names() == {"Pu239", "Pu240"}   # only needs Pu data


def test_downloaded_element_becomes_a_material(tmp_path):
    """Every element the user downloads becomes a selectable pure-element material."""
    active = tmp_path / "cross_sections.xml"
    active.write_text('<?xml version="1.0"?><cross_sections>'
                      '<library materials="U235" path="a" type="neutron"/>'
                      '<library materials="U238" path="b" type="neutron"/>'
                      "</cross_sections>")
    starter = tmp_path / "starter.xml"
    starter.write_text('<?xml version="1.0"?><cross_sections></cross_sections>')
    materials.refresh_auto_materials(str(active), str(starter))
    try:
        spec = materials.LIBRARY["element_U"]
        assert "fuel" in spec.categories                       # actinide → usable as fuel
        assert set(spec.build().get_nuclides()) == {"U235", "U238"}   # only installed isotopes
        assert spec.is_available({"U235", "U238"})
        assert "element_U" in [m.key for m in materials.by_category("fuel")]
        assert materials.build("element_U").density                    # resolves via build()
    finally:
        materials.refresh_auto_materials(None, None)            # restore LIBRARY to catalog
    assert "element_U" not in materials.LIBRARY


def test_categories_and_multi_role_membership():
    fuels = {m.key for m in materials.by_category("fuel")}
    assert {"uo2", "u_metal", "heu_metal_godiva", "mox", "plutonium_metal"} <= fuels
    assert "steel_304" in {m.key for m in materials.by_category("cladding")}
    # water fills two roles
    assert "water" in {m.key for m in materials.by_category("moderator")}
    assert "water" in {m.key for m in materials.by_category("coolant")}


def test_build_respects_enrichment_flag():
    assert "4.5%" in materials.build("uo2", enrichment=4.5).name
    # fixed-composition fuel ignores enrichment
    assert "Godiva" in materials.build("heu_metal_godiva", enrichment=4.5).name


def test_availability_flags_against_bundle():
    L = materials.LIBRARY
    for key in ("uo2", "u_metal", "heu_metal_godiva", "water", "zircaloy", "void"):
        assert L[key].is_available(BUNDLE), key
    for key in ("mox", "graphite", "steel_304", "b4c", "gd2o3"):
        assert not L[key].is_available(BUNDLE), key
    # subtle: heavy water's deuterium IS in the bundle, but its c_D_in_D2O kernel is not
    assert "H2" in BUNDLE
    assert not L["heavy_water"].is_available(BUNDLE)


def test_required_names_enumerated_even_without_data():
    # Gd has no data in the bundle, yet the material's nuclides are still enumerable
    need = materials.LIBRARY["uo2_gd"].required_names()
    assert any(n.startswith("Gd") for n in need)
    assert "c_D_in_D2O" in materials.LIBRARY["heavy_water"].required_names()


def test_missing_data_is_per_material():
    L = materials.LIBRARY
    # exactly the missing elements — collapsed to element symbols for download
    assert L["steel_304"].missing_data(BUNDLE) == (["Cr", "Fe", "Mn", "Ni"], [])
    assert L["mox"].missing_data(BUNDLE) == (["Pu"], [])          # U, O already present
    assert L["graphite"].missing_data(BUNDLE) == (["C"], ["c_Graphite"])
    assert L["heavy_water"].missing_data(BUNDLE) == ([], ["c_D_in_D2O"])  # only the kernel
    # available materials need nothing
    assert L["uo2"].missing_data(BUNDLE) == ([], [])
    assert L["water"].missing_data(BUNDLE) == ([], [])


def test_available_names_parsing(tmp_path):
    xml = tmp_path / "cross_sections.xml"
    xml.write_text(
        '<?xml version="1.0"?><cross_sections>'
        '<library materials="U235" path="a" type="neutron"/>'
        '<library materials="c_H_in_H2O" path="b" type="thermal"/>'
        "</cross_sections>"
    )
    assert materials.available_names(str(xml)) == {"U235", "c_H_in_H2O"}
    assert materials.available_names(None) == set()
    assert materials.available_names(str(tmp_path / "missing.xml")) == set()


def test_template_build_swaps_materials():
    m = templates.pin_cell(fuel="u_metal", moderator="void", batches=10)
    names = [mat.name for mat in m.materials]
    assert any("U metal" in n for n in names)
    assert any("Void" in n for n in names)


def test_bare_sphere_accepts_key_or_object():
    by_key = templates.bare_sphere("u_metal", radius=8.0, batches=10)
    assert "U metal" in by_key.materials[0].name
    obj = materials.uo2(3.0)
    assert templates.bare_sphere(obj, radius=8.0, batches=10).materials[0] is obj


def test_spec_material_roles():
    assert specs.SPECS["Pin cell"].material_defaults() == {
        "fuel": "uo2", "clad": "zircaloy", "moderator": "water"}
    assert specs.SPECS["Godiva"].material_defaults() == {"material": "heu_metal_godiva"}
    assert specs.SPECS["Shield slab"].material_defaults() == {"shield": "water"}
    assert [r.category for r in specs.SPECS["Pin cell"].material_roles] == [
        "fuel", "cladding", "moderator"]
