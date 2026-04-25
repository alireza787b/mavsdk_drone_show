import os
import time
from types import SimpleNamespace

from src.px4_param_models import Px4ParamMetadataSource
from src.px4_params.catalog import (
    _docs_cache_path,
    load_px4_docs_reference_catalog_index,
    parse_px4_parameter_reference_html,
)


def test_parse_px4_parameter_reference_html_extracts_reference_metadata():
    html = """
    <html>
      <body>
        <h2>Multicopter Position Control</h2>
        <h3 id="mpc-xy-cruise">MPC_XY_CRUISE (`FLOAT`)</h3>
        <p>Cruise speed.</p>
        <p>Cruise speed setpoint used for position control.</p>
        <ul>
          <li><code>0</code>: Disabled</li>
          <li><code>1</code>: Enabled</li>
        </ul>
        <table>
          <thead>
            <tr>
              <th>Reboot</th>
              <th>minValue</th>
              <th>maxValue</th>
              <th>increment</th>
              <th>default</th>
              <th>unit</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>&nbsp;</td>
              <td>0.0</td>
              <td>20.0</td>
              <td>0.1</td>
              <td>5.0</td>
              <td>m/s</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """

    rows = parse_px4_parameter_reference_html(html)

    assert rows["MPC_XY_CRUISE"].source == Px4ParamMetadataSource.PX4_DOCS_CACHE
    assert rows["MPC_XY_CRUISE"].group == "Multicopter Position Control"
    assert rows["MPC_XY_CRUISE"].short_description == "Cruise speed."
    assert rows["MPC_XY_CRUISE"].long_description == "Cruise speed.\n\nCruise speed setpoint used for position control."
    assert rows["MPC_XY_CRUISE"].default_value == 5
    assert rows["MPC_XY_CRUISE"].min_value == 0
    assert rows["MPC_XY_CRUISE"].max_value == 20
    assert rows["MPC_XY_CRUISE"].increment == 0.1
    assert rows["MPC_XY_CRUISE"].unit == "m/s"
    assert rows["MPC_XY_CRUISE"].enum_values == [
        {"value": 0, "description": "Disabled"},
        {"value": 1, "description": "Enabled"},
    ]


def test_load_px4_docs_reference_catalog_index_uses_fresh_cache(tmp_path):
    url = "https://docs.px4.io/main/en/advanced_config/parameter_reference.html"
    cache_path = _docs_cache_path(tmp_path, "main", url)
    cache_path.write_text(
        """
        {
          "source": "px4_docs_cache",
          "source_url": "https://docs.px4.io/main/en/advanced_config/parameter_reference.html",
          "version": "main",
          "cached_at": 1,
          "parameters": [
            {
              "name": "MAV_SYS_ID",
              "short_description": "MAVLink system ID",
              "default_value": 1,
              "group": "MAVLink"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    os.utime(cache_path, (time.time(), time.time()))

    params = SimpleNamespace(
        PX4_PARAMETER_ONLINE_DOCS_METADATA_ENABLED=True,
        PX4_PARAMETER_DOCS_VERSION="main",
        PX4_PARAMETER_DOCS_BASE_TEMPLATE="https://docs.px4.io/{version}/en/advanced_config/parameter_reference.html",
        PX4_PARAMETER_METADATA_CACHE_DIR=str(tmp_path),
        PX4_PARAMETER_METADATA_CACHE_TTL_DAYS=14,
        PX4_PARAMETER_METADATA_FETCH_TIMEOUT_SEC=0.5,
        PX4_PARAMETER_METADATA_CACHE_MAX_ENTRIES=4,
    )

    rows = load_px4_docs_reference_catalog_index(params)

    assert rows["MAV_SYS_ID"].source == Px4ParamMetadataSource.PX4_DOCS_CACHE
    assert rows["MAV_SYS_ID"].short_description == "MAVLink system ID"
