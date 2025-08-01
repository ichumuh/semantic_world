import os
import unittest

import plotly.graph_objects as go
from random_events.interval import SimpleInterval
from random_events.product_algebra import SimpleEvent

from semantic_world.adapters.urdf import URDFParser
from semantic_world.geometry import BoundingBox, BoundingBoxCollection
from semantic_world.graph_of_convex_sets import GraphOfConvexSets, PoseOccupiedError
from semantic_world.spatial_types import Point3
from semantic_world.variables import SpatialVariables
from semantic_world.world import World


class GCSTestCase(unittest.TestCase):
    """
    Testcase to test the navigation around a unit box.
    """

    gcs: GraphOfConvexSets

    @classmethod
    def setUpClass(cls):
        gcs = GraphOfConvexSets()

        obstacle = BoundingBox(0, 0, 0, 1, 1, 1)

        z_lim = SimpleInterval(.45, .55)
        x_lim = SimpleInterval(-2, 3)
        y_lim = SimpleInterval(-2, 3)
        limiting_event = SimpleEvent({SpatialVariables.x.value: x_lim,
                                      SpatialVariables.y.value: y_lim,
                                      SpatialVariables.z.value: z_lim,})
        obstacles = BoundingBoxCollection.from_event(
            ~obstacle.simple_event.as_composite_set() & limiting_event.as_composite_set())
        [gcs.add_node(bb) for bb in obstacles]
        gcs.calculate_connectivity()
        cls.gcs = gcs

    def test_reachability(self):
        start_point = Point3.from_xyz(-1, -1, 0.5)
        target_point = Point3.from_xyz(2, 2, 0.5)

        path = self.gcs.path_from_to(start_point, target_point)
        self.assertEqual(len(path), 4)

    def test_plot(self):
        free_space_plot = go.Figure(self.gcs.plot_free_space())
        self.assertIsNotNone(free_space_plot)
        occupied_space_plot = go.Figure(self.gcs.plot_occupied_space())
        self.assertIsNotNone(occupied_space_plot)


class GCSFromWorldTestCase(unittest.TestCase):
    """
    Test the application of a connectivity graph to the belief state.
    """

    world: World

    @classmethod
    def setUpClass(cls):
        urdf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "resources", "urdf")
        apartment = os.path.join(urdf_dir, "table.urdf")
        apartment_parser = URDFParser(apartment)
        cls.world = apartment_parser.parse()

    def test_from_world(self):
        search_space = BoundingBox(min_x=-5, max_x=-2,
                                   min_y=-1, max_y=2,
                                   min_z=0, max_z=2).as_collection()
        gcs = GraphOfConvexSets.free_space_from_world(self.world, search_space=search_space)
        self.assertIsNotNone(gcs)
        self.assertGreater(len(gcs.graph.nodes()), 0)
        self.assertGreater(len(gcs.graph.edges()), 0)

        start = Point3.from_xyz(-4.5, -0.5, 0.4)
        target = Point3.from_xyz(-2.5, 1.5, 0.9)

        path = gcs.path_from_to(start, target)

        self.assertIsNotNone(path)
        self.assertGreater(len(path), 1)

        with self.assertRaises(PoseOccupiedError):
            start = Point3.from_xyz(-10, -10, -10)
            target = Point3.from_xyz(10, 10, 10)
            gcs.path_from_to(start, target)

    def test_navigation_map_from_world(self):
        search_space = BoundingBox(min_x=-5, max_x=-2,
                                   min_y=-1, max_y=2,
                                   min_z=0, max_z=2).as_collection()
        gcs = GraphOfConvexSets.navigation_map_from_world(self.world, search_space=search_space)
        self.assertGreater(len(gcs.graph.nodes()), 0)
        self.assertGreater(len(gcs.graph.edges()), 0)


if __name__ == '__main__':
    unittest.main()