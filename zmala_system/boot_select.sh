# Experimental U-Boot hush selector; also executable with POSIX shell test adapters.
# No kernel is launched here. The caller may load only a nonempty zm_selected.
# Compiled fallback environments MUST omit all zm_* contract fields.
# @llr LLR-SRV-HOST-025, LLR-TERM-MAINT-052, LLR-SRV-HOST-029, LLR-TERM-MAINT-056
setenv zm_selected
setenv zm_is_trial 0
if test "${zm_schema}" = "1"; then
    if test "${zm_role}" = "terminal" || test "${zm_role}" = "server" || test "${zm_role}" = "combined"; then
        if test "${zm_a_good}" = "0" || test "${zm_a_good}" = "1"; then
            if test "${zm_b_good}" = "0" || test "${zm_b_good}" = "1"; then
                if test "${zm_confirmed}" = "A" && test "${zm_a_good}" = "1"; then
                    setenv zm_selected A
                fi
                if test "${zm_confirmed}" = "B" && test "${zm_b_good}" = "1"; then
                    setenv zm_selected B
                fi
            fi
        fi
    fi
fi
if test -n "${zm_selected}"; then
    if test "${zm_trial}" = "-" && test "${zm_left}" = "0"; then
        true
    else
        if test "${zm_left}" = "0" || test "${zm_left}" = "1"; then
            if test "${zm_trial}" = "A" && test "${zm_confirmed}" = "B" && test "${zm_a_good}" = "1"; then
                true
            else
                if test "${zm_trial}" = "B" && test "${zm_confirmed}" = "A" && test "${zm_b_good}" = "1"; then
                    true
                else
                    setenv zm_selected
                fi
            fi
        else
            setenv zm_selected
        fi
        if test -n "${zm_selected}" && test "${zm_left}" = "1"; then
            # Save only stable state: do not persist transient selection outputs.
            setenv zm_selected
            setenv zm_is_trial
            setenv zm_left 0
            if saveenv; then
                setenv zm_selected "${zm_trial}"
                setenv zm_is_trial 1
            else
                setenv zm_selected "${zm_confirmed}"
                setenv zm_is_trial 0
            fi
        fi
    fi
fi
