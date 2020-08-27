# ------------------------------------------------------------------------------------------------ #
# MIT License                                                                                      #
#                                                                                                  #
# Copyright (c) 2020, Microsoft Corporation                                                        #
#                                                                                                  #
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software    #
# and associated documentation files (the "Software"), to deal in the Software without             #
# restriction, including without limitation the rights to use, copy, modify, merge, publish,       #
# distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the    #
# Software is furnished to do so, subject to the following conditions:                             #
#                                                                                                  #
# The above copyright notice and this permission notice shall be included in all copies or         #
# substantial portions of the Software.                                                            #
#                                                                                                  #
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING    #
# BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND       #
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,     #
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,   #
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.          #
# ------------------------------------------------------------------------------------------------ #

import jax
import jax.numpy as jnp
import haiku as hk

from ..utils import get_grads_diagnostics
from ._base import PolicyObjective


class PPOClip(PolicyObjective):
    r"""
    PPO-clip policy objective.

    .. math::

        J(\theta; s,a)\ =\ \min\Big(
            \rho_\theta\,\mathcal{A}(s,a)\,,\
            \bar{\rho}_\theta\,\mathcal{A}(s,a)\Big)

    where :math:`\rho_\theta` and :math:`\bar{\rho}_\theta` are the
    bare and clipped probability ratios, respectively:

    .. math::

        \rho_\theta\ =\
            \frac{\pi_\theta(a|s)}{\pi_{\theta_\text{old}}(a|s)}\ ,
        \qquad
        \bar{\rho}_\theta\ =\
            \big[\rho_\theta\big]^{1+\epsilon}_{1-\epsilon}

    This objective has the property that it allows for slightly more off-policy
    updates than the vanilla policy gradient.


    Parameters
    ----------
    pi : Policy

        The parametrized policy :math:`\pi_\theta(a|s)`.

    optimizer : optax optimizer, optional

        An optax-style optimizer. The default optimizer is :func:`optax.adam(1e-3)
        <optax.adam>`.

    regularizer : PolicyRegularizer, optional

        A policy regularizer, see :mod:`coax.policy_regularizers`.

    epsilon : positive float, optional

        The clipping parameter :math:`\epsilon` that is used to defined the
        clipped importance weight :math:`\bar{\rho}`.

    """
    REQUIRES_PROPENSITIES = True

    def __init__(self, pi, optimizer=None, regularizer=None, epsilon=0.2):
        super().__init__(pi=pi, optimizer=optimizer, regularizer=regularizer)
        self.epsilon = epsilon

    @property
    def hyperparams(self):
        return hk.data_structures.to_immutable_dict({
            'regularizer': getattr(self.regularizer, 'hyperparams', {}),
            'epsilon': self.epsilon})

    def objective_func(self, params, state, hyperparams, rng, transition_batch, Adv):
        rngs = hk.PRNGSequence(rng)

        # get distribution params from function approximator
        S, A, logP = transition_batch[:3]
        dist_params, state_new = self.pi.function(params, state, next(rngs), S, True)

        # compute probability ratios
        A_raw = self.pi.proba_dist.preprocess_variate(A)
        log_pi = self.pi.proba_dist.log_proba(dist_params, A_raw)
        ratio = jnp.exp(log_pi - logP)  # logP is log(π_old)
        ratio_clip = jnp.clip(ratio, 1 - hyperparams['epsilon'], 1 + hyperparams['epsilon'])

        # ppo-clip objective
        assert Adv.ndim == 1, f"bad shape: {Adv.shape}"
        assert ratio.ndim == 1, f"bad shape: {ratio.shape}"
        assert ratio_clip.ndim == 1, f"bad shape: {ratio_clip.shape}"
        objective = jnp.sum(jnp.minimum(Adv * ratio, Adv * ratio_clip))

        # also pass auxiliary data to avoid multiple forward passes
        return objective, (dist_params, log_pi, state_new)
