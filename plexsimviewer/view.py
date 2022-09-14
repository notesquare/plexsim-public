import h5py
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


class H5Viewer:
    def __init__(self, fp):
        all_particles_by_grid = {}
        all_cycles = set()

        with h5py.File(fp, 'r') as h5f:
            shape = h5f['settings/environment'].attrs['grid_shape']
            cell_size = h5f['settings/environment'].attrs['cell_size']
            trajectory_by_grid = {}  # key: (grid_index, species)
            trajectory_by_cycle = {}  # key: cycle, value: { grid: particles }
            stats_by_cycle = {}  # key: cycle, value: n_particles, total_E
            for cycle in sorted(h5f['cycles'], key=int)[:-1]:
                cycle = int(cycle)
                stats = dict(h5f[f'cycles/{cycle}/stats'].attrs)
                n_particles = stats['n_particles']
                total_E = stats['total_E']
                stats_by_cycle[cycle] = dict(n_particles=n_particles,
                                             total_E=total_E)

            for grid_index in sorted(h5f['settings/grids'], key=int):
                grid_index = int(grid_index)
                species = h5f[f'settings/grids/{grid_index}'].attrs['species']
                t_key = (grid_index, species)

                all_particles_by_grid.setdefault(grid_index, set())
                trajectory_by_grid[t_key] = {}
                particles_by_cycles = trajectory_by_grid[t_key]

                for cycle in sorted(h5f['cycles'], key=int)[:-1]:
                    base_path = f'cycles/{cycle}/grids/{grid_index}/tracked'
                    if base_path not in h5f:
                        continue
                    Xs = h5f[f'{base_path}/X'][:]
                    Us = h5f[f'{base_path}/U'][:]
                    ids = h5f[base_path].attrs['tracking_ids']

                    if Xs is None:
                        continue
                    cycle = int(cycle)

                    all_cycles.add(cycle)

                    particles = {}
                    particles_by_cycles.setdefault(cycle, {})
                    for _id, X, U in zip(ids, Xs, Us):
                        all_particles_by_grid[grid_index].add(_id)
                        particles[_id] = (X * cell_size, U)

                    particles_by_cycles[cycle] = particles

                    trajectory_by_cycle.setdefault(cycle, {})
                    trajectory_by_cycle[cycle][t_key] = particles

        self.grid_shape = shape
        self.cell_size = cell_size
        self.trajectory_by_grid = trajectory_by_grid
        self.trajectory_by_cycle = trajectory_by_cycle
        self.stats_by_cycle = stats_by_cycle

        # sort often-used items
        self.all_cycles = sorted(all_cycles)
        self.all_particles_by_grid = {
            k: sorted(v) for k, v in all_particles_by_grid.items()
        }

    def builds_frames(self):
        frames = []
        for cycle in self.all_cycles:
            if cycle not in self.trajectory_by_cycle:
                continue
            grid_data = self.trajectory_by_cycle[cycle]
            frame_data = []
            for grid_key, particles in grid_data.items():
                grid_index, species = grid_key

                p_ids = self.all_particles_by_grid[grid_index]

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

                    legend_text = f'Grid {grid_index} ({species})'
                    frame_data.append(
                        go.Scatter3d(
                            x=[x], y=[y], z=[z],
                            legendgroup=f'g{grid_index}',
                            legendgrouptitle_text=legend_text,
                            mode='markers',
                            name=f'Particle {p_id}',
                            marker=dict(
                                symbol='circle' if species ==
                                        'electron' else 'square'),
                            opacity=0.8
                        )
                    )

            n_traces = len(frame_data)
            n_particles = self.stats_by_cycle[cycle]['n_particles']
            total_E = self.stats_by_cycle[cycle]['total_E']

            frame_data += [go.Scatter(x=[cycle], y=[n_particles]),
                           go.Scatter(x=[cycle], y=[total_E])]
            traces = [i for i in range(n_traces)]\
                + [n_traces * 2 + i for i in range(2)]
            title_text = f'Particles: {n_particles} / Energy {total_E} [J]'
            layout = go.Layout(title_text=title_text)
            frames.append(dict(data=frame_data, name=f'Cycle {cycle}',
                               traces=traces, layout=layout))
        return frames

    def build_traces(self):
        data = []
        for key, particles_by_cycles in self.trajectory_by_grid.items():
            grid_index, species = key

            p_ids = self.all_particles_by_grid[grid_index]

            for p_id in p_ids:
                x = []
                y = []
                z = []

                for cycle in self.all_cycles:
                    particles = particles_by_cycles[cycle]
                    if p_id not in particles:
                        continue

                    X, U = particles[p_id]
                    x.append(X[0])
                    y.append(X[1])
                    z.append(X[2])

                data.append(
                    go.Scatter3d(
                        x=x, y=y, z=z,
                        legendgroup=f'g{grid_index}',
                        mode='lines',
                        opacity=0.3,
                        showlegend=False
                    )
                )
        return data

    @property
    def figure(self):
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
                    'label': f'{k}',
                    'method': 'animate',
                }
                for k, f in enumerate(frames)
            ]
        }]

        fig = make_subplots(rows=2, cols=1,
                            row_heights=[0.8, 0.2],
                            specs=[[{'type': 'scene'}],
                                   [{'type': 'xy', 'secondary_y': True}]])
        fig.frames = frames

        # add trajectory traces
        fig.add_traces([*frames[0]['data'][:-2], *self.build_traces()],
                       rows=1, cols=1)

        # add stats graph
        n_particles_arr = np.array([stat['n_particles'] for stat
                                    in self.stats_by_cycle.values()])
        total_E_arr = np.array([stat['total_E'] for stat
                                in self.stats_by_cycle.values()])
        fig.add_trace(go.Scatter(y=[n_particles_arr[0]],
                                 name='n_particles',
                                 marker=dict(color='red'),
                                 showlegend=False),
                      row=2, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(y=[total_E_arr[0]],
                                 name='total_E',
                                 marker=dict(color='blue'),
                                 showlegend=False),
                      row=2, col=1, secondary_y=True)
        fig.add_trace(go.Scatter(y=n_particles_arr,
                                 name='n_particles',
                                 marker=dict(color='red'),
                                 showlegend=True),
                      row=2, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(y=total_E_arr,
                                 name='total_E',
                                 marker=dict(color='blue'),
                                 showlegend=True),
                      row=2, col=1, secondary_y=True)

        grid_shape = self.grid_shape
        cell_size = self.cell_size
        grid_size = grid_shape * cell_size
        fig.update_layout(
            title={
                'text': fig.frames[0].layout.title.text,
                'font': {'size': 12},
                'pad': {'t': 10, 'b': 10},
                'xanchor': 'left',
                'y': 0.3},
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
            margin=dict(t=20, b=0, l=0, r=0),
            legend=dict(groupclick='toggleitem', x=1.1),
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
            yaxis=dict(title_text='n_particles', exponentformat='SI'),
            yaxis2=dict(title_text='total_E', exponentformat='SI')
        )
        return fig

    def _ipython_display_(self):
        self.figure._ipython_display_()
