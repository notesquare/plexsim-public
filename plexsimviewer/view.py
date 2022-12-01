import os
import re
from pathlib import Path

import h5py
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

COLORS = px.colors.qualitative.Plotly


class H5Viewer:
    def __init__(self, fp, cycles=None):
        fp = Path(fp)

        self.all_particles_by_grid = {}
        self.trajectory_by_grid = {}  # key: particle_name
        self.trajectory_by_cycle = {}
        # key: cycle, value: { particle_name: particles }
        self.stats_by_cycle = {}  # key: cycle, value: stats
        self.particle_name_by_grid_index = {}

        with h5py.File(fp, 'r') as h5f:
            iteration_encoding = h5f.attrs['iterationEncoding'].decode()
            iteration_format = h5f.attrs['iterationFormat'].decode()
            self.grid_shape = h5f['settings'].attrs['grid_shape']
            self.cell_size = h5f['settings'].attrs['cell_size']

        if iteration_encoding == 'fileBased':
            if cycles is None:
                files = []
                for filename in os.listdir(fp.parent):
                    p = re.compile(iteration_format.replace('%T', r'(\d+)'))
                    m = p.match(filename)
                    if not m:
                        continue
                    cycle = m.group(1)
                    files.append(re.sub('%T', cycle,
                                 f'{fp.parent}/{iteration_format}'))
            else:
                files = [
                    re.sub('%T', str(cycle), f'{fp.parent}/{iteration_format}')
                    for cycle in cycles
                ]
            self.collect_data_filebased(files)

        elif iteration_encoding == 'groupBased':
            self.collect_data_groupbased(fp, cycles)

        self.all_particles_by_grid = {
            k: sorted(v) for k, v in self.all_particles_by_grid.items()
        }

        self.figure_tracked = None
        self.figure_stats = None

    def collect_cycle_data(self, h5f, cycle):
        self.stats_by_cycle[cycle] = dict(h5f[f'data/{cycle}/stats'].attrs)
        self.trajectory_by_cycle.setdefault(cycle, {})
        for particle_name in self.particle_name_by_grid_index.values():
            _particle_name = particle_name + '_tracked'
            self.trajectory_by_cycle[cycle].setdefault(_particle_name, {})

        _path = f'data/{cycle}/particles'
        for particle_name in h5f[_path]:
            particle_group = h5f[f'{_path}/{particle_name}']
            if particle_group.attrs['_tracked'] != 1:
                continue

            grid_index = particle_group.attrs['_gridIndex']
            if grid_index not in self.particle_name_by_grid_index:
                _particle_name = particle_name.split('_tracked')[0]
                self.particle_name_by_grid_index[grid_index] = _particle_name

            self.all_particles_by_grid.setdefault(particle_name, set())
            self.trajectory_by_grid.setdefault(particle_name, dict())
            particles_by_cycles = self.trajectory_by_grid[particle_name]

            ids = particle_group['id'][:]
            if len(ids) == 0:
                continue

            axis_labels = ['x', 'y', 'z']
            Xs = np.stack([
                particle_group[f'position/{axis}'][:]
                for axis in axis_labels
            ], axis=-1)
            Us = np.stack([
                particle_group[f'momentum/{axis}'][:]
                for axis in axis_labels
            ], axis=-1)

            particles = {}
            particles_by_cycles.setdefault(cycle, dict())
            for _id, X, U in zip(ids, Xs, Us):
                _id = int(_id)
                self.all_particles_by_grid[particle_name].add(_id)
                particles[_id] = (X * self.cell_size, U)

            particles_by_cycles[cycle] = particles

            self.trajectory_by_cycle[cycle][particle_name] = particles

    def collect_data_filebased(self, files):
        for fp in files:
            with h5py.File(fp, 'r') as h5f:
                cycle = int(set(h5f['data']).pop())
                self.collect_cycle_data(h5f, cycle)

    def collect_data_groupbased(self, fp, cycles=None):
        with h5py.File(fp, 'r') as h5f:
            for cycle in h5f['data']:
                cycle = int(cycle)
                if cycles is not None and cycle not in cycles:
                    continue
                self.collect_cycle_data(h5f, cycle)

    def builds_frames(self):
        frames = []
        for cycle, grid_data in sorted(self.trajectory_by_cycle.items()):
            frame_data = []

            for particle_name, particles in grid_data.items():
                p_ids = self.all_particles_by_grid[particle_name]

                for p_id in p_ids:
                    if p_id not in particles:
                        x = None
                        y = None
                        z = None
                    else:
                        X, U = particles[p_id]
                        x = X[0]
                        y = X[1]
                        z = X[2]

                    color = COLORS[p_id % len(COLORS)]
                    frame_data.append(
                        go.Scatter3d(
                            x=[x], y=[y], z=[z],
                            legendgroup=particle_name,
                            legendgrouptitle_text=particle_name,
                            mode='markers',
                            marker=dict(color=color),
                            name=f'Particle {p_id}',
                            opacity=0.8
                        )
                    )
            frames.append(dict(data=frame_data, name=f'Cycle {cycle}'))
        return frames

    def build_traces(self):
        data = []
        for particle_name, particles_by_cycles\
                in self.trajectory_by_grid.items():

            p_ids = self.all_particles_by_grid[particle_name]
            for p_id in p_ids:
                x = []
                y = []
                z = []

                for cycle, particles in sorted(particles_by_cycles.items()):
                    if p_id not in particles:
                        continue

                    X, U = particles[p_id]
                    x.append(X[0])
                    y.append(X[1])
                    z.append(X[2])

                color = COLORS[p_id % len(COLORS)]
                data.append(
                    go.Scatter3d(
                        x=x, y=y, z=z,
                        legendgroup=particle_name,
                        mode='lines',
                        line=dict(color=color),
                        name=f'Particle {p_id}',
                        opacity=0.3,
                        showlegend=False
                    )
                )
        return data

    def build_figure_tracked(self):
        def frame_args(duration):
            return {
                'frame': {'duration': duration},
                'mode': 'immediate',
                'fromcurrent': True,
                'transition': {'duration': duration, 'easing': 'linear'},
            }

        frames = self.builds_frames()

        sliders = [{
            'pad': {'b': 10, 't': 10},
            'x': 0.1,
            'y': 0,
            'currentvalue': {
                'prefix': 'Cycle: ',
                'visible': True
            },
            'steps': [
                {
                    'args': [[f['name']], frame_args(0)],
                    'label': f['name'].split(' ')[-1],
                    'method': 'animate',
                }
                for f in frames
            ]
        }]

        fig = go.Figure(
            data=[*frames[0]['data'], *self.build_traces()],
            frames=frames)

        grid_shape = self.grid_shape
        cell_size = self.cell_size
        grid_size = grid_shape * cell_size
        fig.update_layout(
            height=800,
            scene=dict(
                xaxis=dict(dtick=cell_size[0], range=[0, grid_size[0]]),
                yaxis=dict(dtick=cell_size[1], range=[0, grid_size[1]]),
                zaxis=dict(dtick=cell_size[2], range=[0, grid_size[2]]),
                aspectmode='manual',
                camera_projection_type='orthographic',
                aspectratio=dict(x=grid_shape[0] / grid_shape.max(),
                                 y=grid_shape[1] / grid_shape.max(),
                                 z=grid_shape[2] / grid_shape.max())
            ),
            margin=dict(t=0, b=0, l=0, r=0),
            updatemenus=[{
                'buttons': [
                    {
                        'args': [None, frame_args(2)],
                        'label': '&#9654;',
                        'method': 'animate',
                    },
                    {
                        'args': [[None], frame_args(0)],
                        'label': '&#9724;',
                        'method': 'animate',
                    },
                ],
                'direction': 'left',
                'pad': {'r': 10, 't': 30},
                'type': 'buttons',
                'x': 0.1,
                'y': 0,
            }],
            sliders=sliders,
        )
        self.figure_tracked = fig

    @property
    def tracked(self):
        if self.figure_tracked is None:
            self.build_figure_tracked()
        self.figure_tracked._ipython_display_()

    def _ipython_display_(self):
        self.tracked

    def build_figure_stats(self):
        stats = sorted(list(self.stats_by_cycle.items()))
        cycles = [cycle for cycle, _ in stats]
        kinetic_E = {
            particle_name: [v['kinetic_E'][grid_index] for _, v in stats]
            for grid_index, particle_name
            in self.particle_name_by_grid_index.items()
        }
        n_particles = {
            particle_name: [v['n_particles'][grid_index] for _, v in stats]
            for grid_index, particle_name
            in self.particle_name_by_grid_index.items()
        }

        fig = make_subplots(specs=[[{'secondary_y': True}]])

        [fig.add_trace(go.Scatter(
            x=cycles,
            y=[v[stat] for _, v in stats],
            name=stat,
            legendgroup='Field Energy'))
         for stat in ['electric_E', 'magnetic_E', 'total_E']]

        [fig.add_trace(go.Scatter(
            x=cycles,
            y=value,
            name=f'kinetic_E-{particle_name}',
            legendgroup='Kinetic Energy'))
         for particle_name, value in kinetic_E.items()]

        [fig.add_trace(go.Scatter(
            x=cycles,
            y=value,
            name=f'n_particles-{particle_name}',
            legendgroup='n_particles'), secondary_y=True)
         for particle_name, value in n_particles.items()]

        fig.update_xaxes(title_text='Cycles')
        fig.update_yaxes(title_text='Energy [J]',
                         tickformat='.3e',
                         secondary_y=False)
        fig.update_yaxes(title_text='# of Particles', secondary_y=True)
        fig.update_layout(title_text='Stats',
                          legend=dict(orientation='h',
                                      yanchor='bottom',
                                      xanchor='right',
                                      x=1,
                                      y=1.02,
                                      groupclick='toggleitem'))
        self.figure_stats = fig

    @property
    def stats(self):
        if self.figure_stats is None:
            self.build_figure_stats()
        self.figure_stats._ipython_display_()
