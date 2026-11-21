import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import App from '../App.vue'

describe('App', () => {
  it('shows JANICE as the main heading', () => {
    const wrapper = mount(App)

    expect(wrapper.get('h1').text()).toBe('JANICE')
  })

  it('spells out what JANICE stands for', () => {
    const wrapper = mount(App)

    expect(wrapper.text()).toContain(
      'Just-in-time Analytics for Network Improvement and Clinical Evaluation',
    )
  })

  it('wraps the page content in a main landmark for screen readers', () => {
    const wrapper = mount(App)

    expect(wrapper.find('main').exists()).toBe(true)
  })
})
